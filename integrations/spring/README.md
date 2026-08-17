# Spring 응급 룰 매칭 이식

Spring 이 자체 응급 hard-stop 을 유지하되, 룰북 계약을 FastAPI 와 동일하게 구현하도록 교체하는 파일들입니다.

## 왜 필요한가

기존 `AiChatEmergencyRuleService` 는 매칭 로직을 직접 구현했고 계약과 어긋났습니다. Rag-Lab 회귀 스위트 66건으로 채점한 결과입니다.

```
미탐            0건
오탐 (RAG 차단)  18건
안내 문구 오류   2건
```

원인 세 가지입니다.

```java
// 기존 normalize(): 공백을 모두 제거
.replaceAll("\\s+", "")

// 그 텍스트에 패턴을 적용 -> '먹고 열이' 가 '고열이' 가 되어 발열 룰이 발동
if (pattern.matcher(normalizedQuestion).find())

// negation_guards 없음 -> '고름은 없어요' 가 응급으로 차단
// 첫 매칭에서 return -> 필러 혈관 경고가 일반 호흡·시야 안내로 대체
```

실제로 차단되던 정상 문의입니다.

```
약을 먹고 열이 내렸어요        붓기가 빠지고 열이 없어요
고름은 없어요                 진물이 나지 않아요
심하게 붓지는 않았어요          눈 통증은 없어요
두드러기는 없어요              극심한 통증은 없어요
```

전부 환자가 증상 부재를 보고하는 문장이고, QA 에서 자연스럽게 입력할 만한 것들입니다.

## 파일

| 파일 | 배치 위치 | 비고 |
| --- | --- | --- |
| `EmergencyRuleMatcher.java` | `src/main/java/com/centerton/centerton/domain/aichat/safety/` | 신규. 매칭 로직 전부 |
| `AiChatEmergencyRuleService.java` | 같은 경로 | 기존 파일 교체. 로딩만 담당 |
| `AiChatEmergencyRuleServiceTest.java` | `src/test/java/com/centerton/centerton/domain/aichat/safety/` | 신규. 회귀 66건 |

패키지 선언이 이미 들어가 있으니 그대로 복사하면 됩니다.

## 반드시 함께 적용해야 하는 것

**테스트를 빼고 매처만 넣으면 안 됩니다.** 지금은 두 구현이 일치하지만, 다음에 룰북이 바뀌면 Java 쪽이 조용히 어긋납니다. 테스트가 있으면 빌드가 깨져서 바로 드러납니다.

테스트는 Rag-Lab 의 `emergency_rule_regression.json` 을 직접 읽습니다. 룰북 경로를 지정해 주세요.

```bash
./gradlew test -Drag.rulebook.root=/opt/centerton/rag_rulebook
```

또는 `RAG_RULEBOOK_ROOT` 환경변수를 사용합니다. 이미 컨테이너에 `/app/rag-rulebook` 으로 마운트하고 있으니 그 값을 쓰면 됩니다.

## 호출부 변경

`findMatch()` 시그니처는 유지했습니다. 다만 `EmergencyRuleMatch` 레코드에 두 필드를 추가해야 합니다.

```java
public record EmergencyRuleMatch(
        String ruleId,
        String ruleName,
        String matchedKeyword,
        String frontendMessage,
        List<String> ruleIds,        // 추가: 매칭된 모든 룰
        List<String> systemActions   // 추가: 매칭된 모든 룰의 system_actions
) {
}
```

`frontendMessage` 는 이제 **매칭된 모든 룰의 안내를 줄바꿈으로 이어붙인 값**입니다. 고름과 발열이 함께 잡히면 두 안내가 모두 전달됩니다. 기존 호출부가 `ruleId()` 와 `frontendMessage()` 만 읽는다면 수정이 필요 없습니다.

전체 목록이 필요하면 `findAllMatches()` 를 쓰세요.

## 검증 상태

`EmergencyRuleMatcher` 의 매칭 로직은 Java 25 에서 회귀 66건을 **실제로 실행해 전부 통과**했습니다.

```
Java 매처: 66건 중 실패 0건

다중 룰 확인: 필러 후 피부가 하얗게 변하고 시야가 흐려요
  RISK-05 via keyword : 시야가흐
  RISK-07 via keyword : 피부가하얗게
  안내 문구 2개 조합됨

다중 룰 확인: 수술 부위에서 노란 고름이 나오고 열이 펄펄 나요.
  RISK-01 via keyword : 고름
  RISK-02 via pattern : 열이 펄펄
```

`AiChatEmergencyRuleService` 와 테스트는 Spring, Lombok, Jackson 3 이 필요해 이 환경에서 컴파일하지 못했습니다. 빌드 오류가 나면 알려 주세요.

Jackson 3 의 `objectNode.properties()` 를 사용합니다. Jackson 2 를 쓰신다면 `fields()` 로 바꿔야 합니다.

## 지켜야 할 계약

```
trigger_keywords   -> compact 형태 (공백 전부 제거)
trigger_patterns   -> spaced 형태 (공백 단일화, 어절 경계 보존)
negation_guards    -> 매칭 span 직후에 앵커링. '안' 은 절대 넣지 않음
반환               -> 매칭된 모든 룰
```

서비스가 기동 시 두 가지를 검사해서 위반이면 예외를 던집니다.

- `normalization.pattern_text_form` 이 `spaced` 가 아니면 거부
- `negation_guards` 가 `^` 로 시작하지 않거나 `안` 을 포함하면 거부

오래된 룰북이 마운트되면 조용히 구버전으로 도는 대신 기동에 실패합니다.
