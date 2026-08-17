# Additional Source Candidates

RAG 코퍼스를 더 단단하게 만들기 위해 다음 출처를 추가 수집 후보로 둡니다. 기본 원칙은 공식 기관, 학회/전문가 단체, 시술별 사후관리와 직접 연결되는 자료를 우선하는 것입니다.

## Priority 1: Korean Official / Regulatory

- [수집 완료] 식품의약품안전처 의료기기 안전사용 정보방: 성형용 필러 안전사용 안내서
  - URL: https://www.mfds.go.kr/brd/m_465/list.do
  - 용도: 필러 부작용, 안전사용, 긴급 상담 기준 후보
  - 권장 버킷: `rag_candidate` 또는 `safety_only`를 문단 단위로 분리
- [수집 완료] 식품의약품안전처 의료용레이저 안전사용 안내서
  - URL: https://www.mfds.go.kr/brd/m_465/view.do?company_cd=&company_nm=&itm_seq_1=0&itm_seq_2=0&multi_itm_seq=0&page=1&seq=27162&srchFr=&srchTo=&srchTp=&srchWord=
  - 용도: 피부 레이저 시술 후 주의사항, 부작용 종류, 병원 문의 기준
  - 권장 버킷: `rag_candidate`
- [수집 완료] 식품의약품안전처 의료용 레이저(피부치료용)
  - URL: https://www.mfds.go.kr/brd/m_464/view.do?company_cd=&company_nm=&itm_seq_1=0&itm_seq_2=0&multi_itm_seq=0&page=3&seq=28291&srchFr=&srchTo=&srchTp=&srchWord=
  - 용도: 레이저 치료 전후 주의사항, 열/자극/자외선 회피
  - 권장 버킷: `rag_candidate`

## Priority 2: Specialty Society / Professional Patient Guidance

- [수집 완료] American Academy of Dermatology: Acne scars after treatment self-care
  - URL: https://www.aad.org/public/diseases/acne/derm-treat/scars/self-care
  - 용도: 여드름 흉터 치료 후 세안, 메이크업, 자외선 차단, 감염 예방
  - 권장 버킷: `rag_candidate`
- [수집 완료] American Academy of Dermatology: Laser treatment for scars
  - URL: https://www.aad.org/public/cosmetic/scars-stretch-marks/laser-treatment-scar
  - 용도: 레이저 전후 주의사항, 자외선, 레티노이드/글리콜릭산 중단, 헤르페스 병력
  - 권장 버킷: `rag_candidate`
- [수집 완료] American Society of Plastic Surgeons: Dermal fillers risks and safety
  - URL: https://www.plasticsurgery.org/cosmetic-procedures/dermal-fillers/safety
  - 용도: 필러 위험 신호, 감염, 피부괴사, 시야 이상
  - 권장 버킷: `safety_only` 우선
- [수집 완료] American Society of Plastic Surgeons: Dermal fillers recovery
  - URL: https://www.plasticsurgery.org/cosmetic-procedures/dermal-fillers/recovery
  - 용도: 필러 후 붓기/멍/활동 제한, 즉시 연락해야 할 증상
  - 권장 버킷: `rag_candidate`와 `safety_only` 혼합
- [수집 완료] American Society of Plastic Surgeons: Rhinoplasty recovery
  - URL: https://www.plasticsurgery.org/cosmetic-procedures/rhinoplasty/recovery
  - 용도: 코성형 회복 기간, 부목/패킹, 붓기 변화, follow-up 질문
  - 권장 버킷: `rag_candidate`

## Collection Notes

- PDF나 HTML을 수집할 때는 원본을 `sources/raw_official/` 또는 별도 `sources/raw_professional/`에 보존합니다.
- 답변 생성에 넣기 전 `rag_candidate`, `safety_only`, `out_of_scope`, `api_reference`로 다시 분류합니다.
- 시야 이상, 심한 통증, 피부 창백/괴사 의심, 호흡곤란, 감염 악화 문단은 일반 RAG보다 hard-stop 룰 근거로 우선합니다.

## Added During Collection

- [수집 완료] FDA Dermal Filler Do's and Don'ts for Wrinkles, Lips, and More
  - URL: https://www.fda.gov/consumers/consumer-updates/dermal-filler-dos-and-donts-wrinkles-lips-and-more
  - 용도: 필러 승인 용도, 일반 부작용, 자가주입/무허가 사용 금지, 보툴리눔 톡신과 구분
  - 권장 버킷: `rag_candidate`와 `safety_only` 혼합
- [수집 완료] FDA Dermal Fillers (Soft Tissue Fillers)
  - URL: https://www.fda.gov/medical-devices/aesthetic-cosmetic-devices/dermal-fillers-soft-tissue-fillers
  - 용도: 필러 혈관 주입 위험, 시야 이상, 뇌졸중 징후, 즉시 진료 기준
  - 권장 버킷: `safety_only`
- [수집 완료] American Society of Plastic Surgeons: Botulinum toxin risks and safety
  - URL: https://www.plasticsurgery.org/cosmetic-procedures/botulinum-toxin/safety
  - 용도: 보툴리눔 톡신 후 호흡/삼킴/말 어눌함/근력 약화 위험 신호
  - 권장 버킷: `safety_only`
- [수집 완료] American Society of Plastic Surgeons: Botulinum toxin recovery
  - URL: https://www.plasticsurgery.org/cosmetic-procedures/botulinum-toxin/recovery
  - 용도: 시술 후 일상 복귀, 문지르기/마사지 회피
  - 권장 버킷: `rag_candidate`
