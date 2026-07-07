# -*- coding: utf-8 -*-
"""
퀴즈 데이터 유효성 검사기.

앱(QuizRepository.parseQuizzes)이 문항 1건이 깨져도 나머지는 살리도록 강화됐지만,
애초에 잘못된 데이터가 main 브랜치에 올라오지 못하게 막는 '게이트' 역할을 한다.
CI(daily_update_.yml)에서 커밋/푸시 직전에 실행되며, 오류가 하나라도 있으면 exit(1)로
파이프라인을 실패시켜 push를 차단한다. (매일 자동 생성분 + 수동 편집분 모두 검사)

과거 사고: knowledge.json의 한 문항 type이 "MULTIPLE_CHOENCE"(오타)여서
앱의 QuizType.valueOf()가 예외 → '상식 백과' 카테고리 100문항이 통째로 안 보였음.
"""

import json
import sys

# Windows 콘솔(cp949) 등에서 이모지 출력 시 크래시하지 않도록 UTF-8로 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

QUIZ_FILES = ["korean.json", "trend.json", "knowledge.json", "travel.json", "quiz_updates.json"]
VALID_TYPES = {"MULTIPLE_CHOICE", "SUBJECTIVE"}
KNOWN_CATEGORIES = {"우리말 겨루기", "트렌드 말하기", "상식 백과", "세계 여행"}
REQUIRED_STR_FIELDS = ["category", "question", "answer", "explanation"]

errors = []    # 하드 오류: 하나라도 있으면 실패(exit 1)
warnings = []  # 소프트 경고: 실패시키지는 않음


def validate_file(file_name, seen_ids):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        warnings.append(f"[{file_name}] 파일이 없습니다 (건너뜀).")
        return
    except json.JSONDecodeError as e:
        errors.append(f"[{file_name}] JSON 파싱 실패: {e}")
        return

    if not isinstance(data, list):
        errors.append(f"[{file_name}] 최상위가 배열(list)이 아닙니다.")
        return

    for idx, q in enumerate(data):
        loc = f"[{file_name}] index={idx}"
        if not isinstance(q, dict):
            errors.append(f"{loc}: 객체(object)가 아닙니다.")
            continue

        qid = q.get("id")
        loc = f"[{file_name}] id={qid} (index={idx})"

        # id: 정수 + 전역 유니크
        if not isinstance(qid, int) or isinstance(qid, bool):
            errors.append(f"{loc}: id가 정수가 아닙니다 ({qid!r}).")
        else:
            if qid in seen_ids:
                errors.append(f"{loc}: id가 중복됩니다 (이미 {seen_ids[qid]}에 존재).")
            else:
                seen_ids[qid] = file_name

        # type: 정확히 규격값
        qtype = q.get("type")
        if qtype not in VALID_TYPES:
            errors.append(f"{loc}: type이 올바르지 않습니다 ({qtype!r}). {VALID_TYPES} 중 하나여야 함.")

        # 필수 문자열 필드
        for field in REQUIRED_STR_FIELDS:
            val = q.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"{loc}: '{field}'가 비어있거나 문자열이 아닙니다 ({val!r}).")

        # 카테고리 화이트리스트 (알 수 없으면 경고)
        cat = q.get("category")
        if cat not in KNOWN_CATEGORIES:
            warnings.append(f"{loc}: 알 수 없는 category '{cat}' (앱 isDefault 목록 갱신 필요할 수 있음).")

        options = q.get("options")
        if qtype == "MULTIPLE_CHOICE":
            # 보기 정확히 4개, 모두 비어있지 않은 문자열, 서로 중복 아님
            if not isinstance(options, list) or len(options) != 4:
                errors.append(f"{loc}: MULTIPLE_CHOICE인데 options가 4개가 아닙니다 ({options!r}).")
            else:
                if any((not isinstance(o, str)) or (not o.strip()) for o in options):
                    errors.append(f"{loc}: options에 비어있거나 문자열 아닌 항목이 있습니다 ({options!r}).")
                if len(set(options)) != len(options):
                    errors.append(f"{loc}: options에 중복된 보기가 있습니다 ({options!r}).")
                ans = q.get("answer")
                if isinstance(ans, str) and ans not in options:
                    errors.append(f"{loc}: answer('{ans}')가 options 안에 없습니다 ({options!r}).")
        elif qtype == "SUBJECTIVE":
            # 주관식은 보기가 없어야 함 (있으면 경고 — 앱은 무시하지만 데이터 정합성 차원)
            if options is not None:
                warnings.append(f"{loc}: SUBJECTIVE인데 options가 있습니다 (null 권장).")


def main():
    seen_ids = {}
    for fn in QUIZ_FILES:
        validate_file(fn, seen_ids)

    if warnings:
        print("⚠️ 경고 (실패 아님):")
        for w in warnings:
            print("  - " + w)

    if errors:
        print(f"\n❌ 유효성 검사 실패: 오류 {len(errors)}건")
        for e in errors:
            print("  - " + e)
        sys.exit(1)

    print(f"\n✅ 유효성 검사 통과 — 총 {len(seen_ids)}개 문항, 오류 0건.")


if __name__ == "__main__":
    main()
