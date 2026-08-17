package com.centerton.centerton.domain.aichat.safety;

import com.centerton.centerton.domain.aichat.safety.EmergencyRuleMatcher.RuleHit;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Spring 구현이 룰북 계약을 지키는지 검증한다.
 *
 * <p>Rag-Lab 의 {@code emergency_rule_regression.json} 을 그대로 읽어 실행한다.
 * FastAPI 와 같은 파일을 쓰기 때문에 두 구현이 어긋나면 여기서 실패한다.
 * 이 테스트 없이 {@link EmergencyRuleMatcher} 만 유지하면 조용히 갈라진다.
 *
 * <p>룰북 경로는 시스템 프로퍼티나 환경변수로 지정한다.
 *
 * <pre>
 * ./gradlew test -Drag.rulebook.root=/opt/centerton/rag_rulebook
 * </pre>
 */
class AiChatEmergencyRuleServiceTest {

    private static EmergencyRuleMatcher matcher;
    private static JsonNode suite;
    private static String rulebookVersion;

    private static Path rulebookRoot() {
        String configured = System.getProperty("rag.rulebook.root",
                System.getenv("RAG_RULEBOOK_ROOT"));
        if (configured == null || configured.isBlank()) {
            throw new IllegalStateException(
                    "rag.rulebook.root 시스템 프로퍼티 또는 RAG_RULEBOOK_ROOT 환경변수가 필요합니다."
            );
        }
        return Path.of(configured);
    }

    @BeforeAll
    static void loadFixtures() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        Path root = rulebookRoot();

        JsonNode rules = mapper.readTree(
                Files.newInputStream(root.resolve("rules/emergency_rules.json")));
        suite = mapper.readTree(
                Files.newInputStream(root.resolve("test_cases/emergency_rule_regression.json")));

        rulebookVersion = rules.path("version").asText();
        // 프로덕션과 같은 파싱 경로를 쓴다. 테스트가 자체 로더를 갖게 되면 그 로더가 갈라진다.
        matcher = AiChatEmergencyRuleService.buildMatcher(rules);
    }

    @Test
    @DisplayName("회귀 스위트가 배포된 룰북 버전을 고정한다")
    void suitePinsRulebookVersion() {
        assertEquals(rulebookVersion, suite.path("rulebook_version").asText(),
                "룰북과 회귀 스위트 버전이 어긋났습니다");
    }

    @Test
    @DisplayName("회귀 스위트 전체를 통과한다")
    void allRegressionCasesPass() {
        List<String> failures = new ArrayList<>();

        for (JsonNode testCase : suite.path("cases")) {
            String id = testCase.path("id").asText();
            String expect = testCase.path("expect").asText();
            String input = testCase.path("user_input").asText();

            List<RuleHit> hits = matcher.match(input);
            Set<String> fired = new LinkedHashSet<>();
            for (RuleHit hit : hits) {
                fired.add(hit.ruleId());
            }

            if ("hard_stop".equals(expect) && hits.isEmpty()) {
                failures.add(id + ": hard_stop 기대인데 매칭 없음 — " + input);
            }
            if ("no_match".equals(expect) && !hits.isEmpty()) {
                failures.add(id + ": no_match 기대인데 " + fired + " 발동 — " + input);
            }

            Set<String> required = stringSet(testCase.path("expected_rule_ids"));
            if (!required.isEmpty() && !fired.containsAll(required)) {
                Set<String> missing = new LinkedHashSet<>(required);
                missing.removeAll(fired);
                failures.add(id + ": " + missing + " 누락, 실제 " + fired);
            }

            Set<String> forbidden = stringSet(testCase.path("forbidden_rule_ids"));
            forbidden.retainAll(fired);
            if (!forbidden.isEmpty()) {
                failures.add(id + ": 금지 룰 " + forbidden + " 발동 — " + input);
            }
        }

        assertTrue(failures.isEmpty(),
                failures.size() + "건 위반\n" + String.join("\n", failures));
    }

    @Test
    @DisplayName("공백 제거로 생기는 오탐이 없다")
    void wordBoundaryFalsePositives() {
        // 공백을 제거하면 '먹고'+'열이' 가 '고열이' 를 만든다.
        assertFalse(matcher.isHardStop("약을 먹고 열이 내렸어요"));
        assertFalse(matcher.isHardStop("붓기가 빠지고 열이 없어요"));
        // '회복시기' 안의 '복시', '발목이 붓' 안의 '목이 붓'
        assertFalse(matcher.isHardStop("회복시기가 언제쯤인지 궁금해요"));
        assertFalse(matcher.isHardStop("발목이 붓어서 걷기 불편해요"));
    }

    @Test
    @DisplayName("증상 부재 보고를 응급으로 차단하지 않는다")
    void negationIsSuppressed() {
        assertFalse(matcher.isHardStop("고름은 없어요"));
        assertFalse(matcher.isHardStop("진물이 나지 않아요"));
        assertFalse(matcher.isHardStop("심하게 붓지는 않았어요"));
    }

    @Test
    @DisplayName("증상 지속을 뜻하는 부정어는 여전히 응급이다")
    void persistenceIsStillEmergency() {
        // '안' 을 억제 토큰으로 쓰면 이 네 건이 모두 미탐된다.
        assertTrue(matcher.isHardStop("열이 안 떨어져요"));
        assertTrue(matcher.isHardStop("피가 안 멈춰요"));
        assertTrue(matcher.isHardStop("눈이 안 보여요"));
        assertTrue(matcher.isHardStop("고름이 나오고 통증은 없어요"));
    }

    @Test
    @DisplayName("매칭된 모든 룰의 안내 문구를 전달한다")
    void allMatchedRulesContributeGuidance() {
        List<RuleHit> hits = matcher.match("필러 후 피부가 하얗게 변하고 시야가 흐려요");
        Set<String> fired = new LinkedHashSet<>();
        for (RuleHit hit : hits) {
            fired.add(hit.ruleId());
        }

        // 첫 룰만 반환하면 필러 전용 안내가 일반 호흡·시야 안내로 바뀐다.
        assertTrue(fired.contains("RISK-07"), "필러 혈관 경고가 누락되었습니다: " + fired);
        assertTrue(EmergencyRuleMatcher.buildMessage(hits).contains("필러"),
                "안내 문구에 필러 관련 지시가 없습니다");
    }

    @Test
    @DisplayName("고름과 발열이 함께 잡힌다")
    void infectionAndFeverFireTogether() {
        List<RuleHit> hits = matcher.match("수술 부위에서 노란 고름이 나오고 열이 펄펄 나요.");
        Set<String> fired = new LinkedHashSet<>();
        for (RuleHit hit : hits) {
            fired.add(hit.ruleId());
        }
        assertTrue(fired.contains("RISK-01"), fired.toString());
        assertTrue(fired.contains("RISK-02"), fired.toString());
    }

    private static Set<String> stringSet(JsonNode arrayNode) {
        Set<String> values = new LinkedHashSet<>();
        if (arrayNode.isArray()) {
            for (JsonNode item : arrayNode) {
                values.add(item.asText());
            }
        }
        return values;
    }
}
