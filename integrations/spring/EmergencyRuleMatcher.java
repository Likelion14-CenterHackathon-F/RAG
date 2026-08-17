package com.centerton.centerton.domain.aichat.safety;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 응급 hard-stop 룰 매칭. {@code rag_rulebook/rules/emergency_rules.json} 의 계약을 구현한다.
 *
 * <p>Python 참조 구현인 {@code rag_rulebook/tools/emergency_matcher.py} 와 동일하게 동작해야 한다.
 * 두 구현이 갈라지면 Spring 이 차단한 것과 FastAPI 가 차단한 것이 달라진다.
 * 그래서 {@code emergency_rule_regression.json} 의 66건을 양쪽에서 모두 검증한다.
 * {@code AiChatEmergencyRuleServiceTest} 를 함께 유지하지 않으면 이 클래스는 조용히 어긋난다.
 *
 * <p>계약의 핵심 세 가지.
 *
 * <ol>
 *   <li>정규화 형태가 두 개다. {@code trigger_keywords} 는 공백을 모두 제거한 compact 형태에서,
 *       {@code trigger_patterns} 는 공백을 보존한 spaced 형태에서 평가한다.
 *       공백을 제거하면 어절 경계가 사라져 환자가 쓰지 않은 토큰이 생긴다.
 *       "약을 먹고 열이 내렸어요" 는 "약을먹고열이내렸어요" 가 되어 "고열이" 를 포함하므로
 *       고열 룰이 안심 문의를 응급으로 차단한다. 경계가 이미 소실되어 lookbehind 로도 복구할 수 없다.
 *   <li>{@code negation_guards} 를 매칭된 span 직후에 앵커링해 평가한다. 앵커링하지 않으면
 *       "고름이 나오고 통증은 없어요" 에서 통증에 붙은 부정이 고름 트리거를 취소해
 *       실제 감염 신호가 사라진다.
 *   <li>매칭된 모든 룰을 반환한다. 첫 룰에서 반환하면 필러 혈관 경고(RISK-07)가
 *       일반 호흡·시야 안내(RISK-05)로 바뀌어 환자가 잘못된 지시를 받는다.
 * </ol>
 *
 * <p>부정어 "안" 은 억제 토큰에 절대 넣지 않는다. 한국어에서 트리거 뒤의 "안" 은
 * 증상이 지속된다는 뜻이므로 "열이 안 떨어져요", "피가 안 멈춰요", "눈이 안 보여요" 는
 * 모두 실제 응급이다.
 */
public final class EmergencyRuleMatcher {

    private static final String POLICY_KEYWORD_OR_PATTERN = "any_keyword_or_pattern";
    private static final Pattern WHITESPACE = Pattern.compile("\\s+");

    private final List<EmergencyRule> rules;
    private final List<Pattern> negationGuards;
    private final Map<String, String> numberAliases;

    public EmergencyRuleMatcher(
            List<EmergencyRule> rules,
            List<Pattern> negationGuards,
            Map<String, String> numberAliases
    ) {
        this.rules = List.copyOf(rules);
        this.negationGuards = List.copyOf(negationGuards);
        this.numberAliases = Map.copyOf(numberAliases);
    }

    // ------------------------------------------------------------------ 정규화

    private String applyAliases(String text) {
        String result = text;
        for (Map.Entry<String, String> entry : numberAliases.entrySet()) {
            result = result.replace(entry.getKey(), entry.getValue());
        }
        return result;
    }

    /** {@code trigger_keywords} 평가용. 공백을 모두 제거한다. */
    String normalizeCompact(String value) {
        String text = Normalizer.normalize(value, Normalizer.Form.NFC).toLowerCase();
        text = WHITESPACE.matcher(text).replaceAll("");
        return applyAliases(text);
    }

    /** {@code trigger_patterns} 평가용. 공백을 단일 공백으로 축약해 어절 경계를 보존한다. */
    String normalizeSpaced(String value) {
        String text = Normalizer.normalize(value, Normalizer.Form.NFC).toLowerCase();
        text = WHITESPACE.matcher(text).replaceAll(" ").strip();
        return applyAliases(text);
    }

    // -------------------------------------------------------------- 부정 억제

    /**
     * 트리거 직후의 텍스트가 증상 부재를 보고하는지 판단한다.
     *
     * <p>guard 는 모두 {@code ^} 로 시작하므로 remainder 의 시작에만 매칭된다.
     * 앵커링이 사라지면 문장 뒤쪽의 무관한 부정이 실제 응급을 취소한다.
     */
    boolean isNegated(String remainder) {
        for (Pattern guard : negationGuards) {
            if (guard.matcher(remainder).find()) {
                return true;
            }
        }
        return false;
    }

    // ------------------------------------------------------------------ 매칭

    private RuleHit keywordHit(EmergencyRule rule, String compact) {
        for (String keyword : rule.keywords()) {
            String needle = normalizeCompact(keyword);
            if (needle.isEmpty()) {
                continue;
            }
            int start = compact.indexOf(needle);
            while (start >= 0) {
                int end = start + needle.length();
                // 모든 출현을 확인한다. 첫 출현만 보면
                // "고름은 없지만 다른 곳에서 고름이 나와요" 가 미탐된다.
                if (!isNegated(compact.substring(end))) {
                    return new RuleHit(rule.id(), rule.name(), "keyword", keyword, needle,
                            rule.frontendMessage(), rule.systemActions());
                }
                start = compact.indexOf(needle, start + 1);
            }
        }
        return null;
    }

    private RuleHit patternHit(EmergencyRule rule, String spaced) {
        for (Pattern pattern : rule.patterns()) {
            Matcher matcher = pattern.matcher(spaced);
            while (matcher.find()) {
                if (!isNegated(spaced.substring(matcher.end()))) {
                    return new RuleHit(rule.id(), rule.name(), "pattern", pattern.pattern(),
                            matcher.group(), rule.frontendMessage(), rule.systemActions());
                }
            }
        }
        return null;
    }

    /** 매칭된 모든 룰을 룰북 선언 순서대로 반환한다. */
    public List<RuleHit> match(String question) {
        if (question == null || question.isBlank()) {
            return List.of();
        }

        String compact = normalizeCompact(question);
        String spaced = normalizeSpaced(question);
        List<RuleHit> hits = new ArrayList<>();

        for (EmergencyRule rule : rules) {
            RuleHit hit = keywordHit(rule, compact);
            if (hit == null && POLICY_KEYWORD_OR_PATTERN.equals(rule.matchPolicy())) {
                hit = patternHit(rule, spaced);
            }
            if (hit != null) {
                hits.add(hit);
            }
        }
        return List.copyOf(hits);
    }

    public boolean isHardStop(String question) {
        return !match(question).isEmpty();
    }

    /** 매칭된 모든 룰의 안내 문구를 중복 없이 이어붙인다. */
    public static String buildMessage(List<RuleHit> hits) {
        Map<String, Boolean> seen = new LinkedHashMap<>();
        for (RuleHit hit : hits) {
            String message = hit.frontendMessage() == null ? "" : hit.frontendMessage().strip();
            if (!message.isEmpty()) {
                seen.putIfAbsent(message, Boolean.TRUE);
            }
        }
        return String.join("\n", seen.keySet());
    }

    /** 매칭된 모든 룰의 system_actions 를 중복 없이 모은다. */
    public static List<String> collectSystemActions(List<RuleHit> hits) {
        Map<String, Boolean> seen = new LinkedHashMap<>();
        for (RuleHit hit : hits) {
            for (String action : hit.systemActions()) {
                seen.putIfAbsent(action, Boolean.TRUE);
            }
        }
        return List.copyOf(seen.keySet());
    }

    // ------------------------------------------------------------------ 타입

    public record EmergencyRule(
            String id,
            String name,
            List<String> keywords,
            List<Pattern> patterns,
            String matchPolicy,
            String frontendMessage,
            List<String> systemActions
    ) {
    }

    public record RuleHit(
            String ruleId,
            String ruleName,
            String matchedBy,
            String evidence,
            String matchedText,
            String frontendMessage,
            List<String> systemActions
    ) {
    }
}
