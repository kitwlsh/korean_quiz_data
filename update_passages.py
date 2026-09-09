# -*- coding: utf-8 -*-
"""
매일 «읽기 지문» 1편을 만들어 passages_<연도>.json 에 쌓는다. (2026-09-07 신설)

KDailyUtil의 「빠른 독서 훈련」은 오랫동안 **앱에 하드코딩된 19편**으로만 돌았다.
지문을 늘리려면 앱을 새로 빌드·업로드해야 했고, 매일 하면 19일에 한 바퀴가 돌아
그 뒤로는 «재독»이 된다. 재독이면 WPM이 오르지만 그건 실력이 아니라 내용을 아는 것이라,
앱이 보여 주는 WPM 추이 그래프까지 왜곡된다. 그래서 공급원을 만든다.

왜 이 저장소인가 (KDailyUtil/doc/FEATURE_DAILY_PASSAGES.md §2)
  이미 여기에 **모델 폴백·실패 이슈 자동생성·생존 신호·QUIZ_MODEL 비상 레버**가 있고
  실측으로 검증됐다. 새 저장소를 만들면 그 방어를 통째로 복제하고 감시 대상을 하나 늘린다.

🔴 왜 update_quiz.py 안에 넣지 않았나 (§8)
  퀴즈 생성이 실패해도 지문은 저장되어야 하고, 그 반대도 되어야 한다.
  한 스크립트·한 API 호출에 둘을 섞으면 한쪽 실패가 다른 쪽을 끌고 죽는다.
  → **별도 스크립트 + 워크플로의 별도 스텝**으로 두고, 생존 신호에는 `passages` 블록만 얹는다.

⚠️ 모델 폴백 헬퍼가 update_quiz.py와 중복돼 있다. 그 파일은 함수가 아니라 **위에서 아래로
   실행되는 스크립트**라 import하면 퀴즈 생성이 그대로 돌아 버린다. 중복이 그 대가보다 싸다.
   (규칙 자체는 앱 GeminiManager와 같다: 404·503이면 다음 후보 / 429·키 오류는 즉시 중단)
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import google.generativeai as genai

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("오류: GEMINI_API_KEY 환경변수가 없습니다. GitHub Secrets를 확인해 주세요.")
    exit(1)

genai.configure(api_key=API_KEY)

MODEL_CANDIDATES = [
    m for m in [
        os.environ.get("QUIZ_MODEL", "").strip(),  # 🔧 비상 레버(Actions 변수) — 퀴즈와 같은 레버를 쓴다
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
    ] if m
]

HEARTBEAT_FILE = "last_run.json"

# ── 규격 (KDailyUtil/doc/FEATURE_DAILY_PASSAGES.md §3·§7·§11) ────────────────
# 하루 1편. 🔴 3편 이상 만들지 않는다 — 소비 속도를 넘으면 «못 본 지문»이 쌓여 부담이 된다(§9).
PASSAGES_PER_RUN = 1

# 🔴 429는 «치명적»이 아니다(2026-09-09 실측 - 창이 수십 초다). 퀴즈 쪽과 같은 값을 쓴다.
RETRY_ON_429 = 2
RETRY_SLEEP_CAP = 90
QUOTA_WAITS = 0
# 200자 ± 50자. 내장 19편이 150~200자 안팎이고, RSVP·페이서 한 세션에 맞는 크기다.
MIN_CHARS = 150
MAX_CHARS = 250
# 프롬프트에 넣어 «같은 글을 다시 쓰지 않게» 하는 회피 목록 크기(최근 것부터).
AVOID_RECENT = 40

# 내장 19편이 쓰던 17개 주제. 날짜로 돌려 한 주제가 몰리지 않게 한다.
THEMES = [
    "독서·읽기", "자연·숲", "우주·별", "바다·생태", "기술·도구", "습관·성장",
    "역사·기록", "여행", "요리", "건강·운동", "계절·날씨", "음악·예술",
    "도시·건축", "동물", "시간·철학", "식물", "경제·돈 상식",
]


def _looks_like(err_text, needles):
    low = str(err_text).lower()
    return any(n in low for n in needles)


def is_model_unavailable(err):
    """404(모델 없음)·503(과부하) → 다음 후보로 넘어갈 만한 실패인가."""
    return _looks_like(err, ["404", "not found", "is not supported", "503", "unavailable", "overloaded"])


def is_key_error(err):
    """키·권한 문제. 자거나 모델을 바꿔도 소용없다 -> 즉시 멈춘다."""
    return _looks_like(err, ["api key", "api_key", "permission", "401", "403"])


def is_quota_error(err):
    """429(한도 초과).

    🔴 **2026-09-09 실측으로 다루는 법이 바뀌었다**(KDailyUtil/doc/AI_KEY_NOTES.md 3-2).
      - 창이 «수십 초»다 - 오류가 `Please retry in 9.4s`처럼 직접 말해 주고, 65초 뒤엔 풀렸다
      - 한도가 «모델마다 다르다» - 같은 키·같은 날에 `gemini-3.8-flash`=5 / `gemini-3.5-flash`=20
    ⚠️ 08-25에는 «한도는 키 단위라 모델을 바꿔도 그대로»로 보고 **즉시 중단**했다.
       그 전제가 실측으로 뒤집혀서 지금은 **«자고 재시도 -> 그래도 막히면 다음 모델»**이다.
    🔴 키 문제(401·403)는 여기서 뺐다 - 그것은 자도 낫지 않는다."""
    return _looks_like(err, ["429", "resource_exhausted", "quota"])


def retry_after_seconds(err, default=20):
    """오류 본문의 «Please retry in 12.3s»를 그대로 쓴다(없으면 기본값·상한 적용)."""
    m = re.search(r"retry in ([0-9.]+)s", str(err), re.IGNORECASE)
    wait = float(m.group(1)) + 2 if m else float(default)
    return int(min(max(wait, 5), RETRY_SLEEP_CAP))


def year_file(year=None):
    """🔴 연도로 쪼갠다 — 앱은 동기화 때마다 파일 전체를 다시 받는다(조건부 요청이 없다).
    퀴즈가 이미 매 동기화 438KB인 길을 갔다. 연도로 나누면 앱은 «올해+작년» 2개만 받으면 된다."""
    y = year or datetime.now(timezone.utc).year
    return "passages_{}.json".format(y)


def load_passages(file_name):
    if not os.path.exists(file_name):
        return []
    try:
        with open(file_name, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        # 🔴 여기서 빈 목록을 돌려주면 이번 실행이 **기존 지문을 덮어써 날려 버린다**.
        print("기존 지문 파일을 읽을 수 없습니다({}): {}".format(file_name, e))
        raise


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def merge_heartbeat(block):
    """생존 신호에 `passages` 블록만 얹는다.

    같은 워크플로에서 **퀴즈 스텝이 먼저 돌아 last_run.json을 새로 쓰고**, 이 스크립트가
    그 위에 자기 칸만 병합한다. 그래서 지문만 실패한 날도 파일 하나로 구별된다.
    """
    payload = {}
    if os.path.exists(HEARTBEAT_FILE):
        try:
            with open(HEARTBEAT_FILE, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            payload = {}
    payload["passages"] = block
    try:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("🫀 생존 신호에 지문 블록 기록: {} (누적 {}편)".format(block.get("status"), block.get("total")))
    except Exception as e:
        print("생존 신호 기록 실패(무시하고 계속): {}".format(e))


def fail(message, model_used=None, total=None):
    """조용히 사라지지 않는다 — 실패도 생존 신호에 남기고 죽는다(워크플로가 이슈를 연다)."""
    print("문제 발생: {}".format(message))
    merge_heartbeat({
        "status": "failed",
        "ranAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model_used,
        "savedThisRun": 0,
        "total": total,
        "error": str(message)[:500],
    })
    exit(1)


def generate_with_fallback(prompt):
    """🔴 이 스크립트도 실행당 API를 «한 번»만 부른다 — 429는 우리가 몰아 친 결과가 아니라
    한도가 짜기 때문이다(2026-09-09 실측). 대응 = 자고 다시 묻기 + 모델 바꾸기."""
    global QUOTA_WAITS
    last_error = None
    for name in MODEL_CANDIDATES:
        for attempt in range(RETRY_ON_429 + 1):
            try:
                print("모델 시도: {}{}".format(name, " (재시도 {})".format(attempt) if attempt else ""))
                response = genai.GenerativeModel(name).generate_content(prompt)
                print("✅ 모델 {} 응답 성공".format(name))
                return response, name
            except Exception as e:
                last_error = e
                if is_key_error(e):
                    fail("키 또는 권한 문제로 중단: {}".format(e), model_used=name)
                if is_quota_error(e):
                    if attempt < RETRY_ON_429:
                        wait = retry_after_seconds(e)
                        QUOTA_WAITS += 1
                        print("  ⏳ {} 한도 초과(429) — {}초 자고 다시 묻는다".format(name, wait))
                        time.sleep(wait)
                        continue
                    print("  ↪ {} 한도 초과(429)가 계속된다 — 다음 후보로".format(name))
                    break
                if is_model_unavailable(e):
                    print("  ↪ {} 사용 불가({}) — 다음 후보로".format(name, str(e)[:120]))
                    break
                print("  ↪ {} 실패({}) — 다음 후보로".format(name, str(e)[:120]))
                break
    fail("모든 후보 모델이 실패했습니다. 마지막 사유: {}".format(last_error))


def theme_of_day(today):
    return THEMES[today.timetuple().tm_yday % len(THEMES)]


def build_prompt(today, existing):
    """저작권 가드가 프롬프트의 절반이다 — §7의 허용 경로 ③(AI 생성 원문)만 쓴다."""
    theme = theme_of_day(today)
    recent = existing[-AVOID_RECENT:]
    avoid_lines = "\n".join(
        "- {} / {}…".format(p.get("title", ""), str(p.get("text", ""))[:40]) for p in recent
    ) or "- (아직 없음)"

    return """당신은 한국어 읽기 훈련용 «짧은 산문»을 쓰는 작가입니다.
아래 조건을 모두 지켜 **오늘의 지문 {count}편**을 새로 창작해 주세요.

[주제] {theme}
[길이] 본문 {min_chars}~{max_chars}자 (한국어 기준, 공백 포함)
[문체] 평서문 위주의 담백한 산문. 3~5개 문장. 대화·따옴표·목록·이모지 없이.
[내용] 일반 상식이나 보편적인 관찰을 자기 문장으로 풀어쓴 창작물. 마지막 문장에 작은 통찰 한 줄.

🔴 반드시 지킬 금지 사항 (어기면 사용할 수 없습니다)
1. 실존하는 작품·기사·가사·시·소설의 문장을 그대로 쓰거나 요약·번안하지 마세요. **새로 쓴 글만.**
2. 실존 인물, 상표, 특정 기업·제품 이름을 넣지 마세요.
3. 특정 국가·집단·종교·정치에 대한 평가를 넣지 마세요.
4. 통계·연도·수치를 단정적으로 주장하지 마세요(사실 확인이 불가능합니다).
5. 아래 «이미 있는 지문»과 같은 소재·전개를 반복하지 마세요.

[이미 있는 지문 — 이것과 겹치지 않게]
{avoid}

[출력 형식] 설명 없이 **JSON 배열만** 출력하세요. 마크다운 코드블록도 쓰지 마세요.
[
  {{
    "title": "짧은 제목(12자 이내)",
    "theme": "{theme}",
    "text": "본문 {min_chars}~{max_chars}자"
  }}
]
""".format(
        count=PASSAGES_PER_RUN,
        theme=theme,
        min_chars=MIN_CHARS,
        max_chars=MAX_CHARS,
        avoid=avoid_lines,
    )


def parse_items(raw_text):
    """AI가 코드블록·군더더기를 붙여 보내는 일이 잦다 → JSON 배열만 도려낸다."""
    text = str(raw_text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON 배열을 찾을 수 없습니다: {}".format(text[:200]))
    items = json.loads(text[start:end + 1])
    if not isinstance(items, list):
        raise ValueError("최상위가 배열이 아닙니다.")
    return items


def next_id(today, existing):
    """id = YYYYMMDD + 일련번호 3자리. 사람이 보고 언제 것인지 바로 안다."""
    base = int(today.strftime("%Y%m%d")) * 1000
    used = {p.get("id") for p in existing}
    candidate = base + 1
    while candidate in used:
        candidate += 1
    return candidate


def main():
    today = datetime.now(timezone.utc)
    file_name = year_file()

    try:
        existing = load_passages(file_name)
    except Exception as e:
        fail("기존 지문 파일 파싱 실패 — 덮어쓰지 않고 중단합니다: {}".format(e))
        return

    seen_titles = {norm(p.get("title")) for p in existing}
    seen_texts = {norm(p.get("text")) for p in existing}

    response, model_used = generate_with_fallback(build_prompt(today, existing))

    try:
        items = parse_items(getattr(response, "text", ""))
    except Exception as e:
        fail("응답 파싱 실패: {}".format(e), model_used=model_used, total=len(existing))
        return

    saved = 0
    skipped = {"length": 0, "duplicate": 0, "malformed": 0}

    for item in items[:PASSAGES_PER_RUN]:
        if not isinstance(item, dict):
            skipped["malformed"] += 1
            continue
        title = str(item.get("title", "")).strip().replace("\n", " ")[:20]
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        theme = str(item.get("theme", "")).strip() or theme_of_day(today)

        if not title or not text:
            skipped["malformed"] += 1
            print("  ↪ 제목·본문이 비어 건너뜀")
            continue
        # 길이 가드: 짧으면 훈련이 안 되고, 길면 RSVP 한 세션을 넘긴다.
        if not (MIN_CHARS <= len(text) <= MAX_CHARS):
            skipped["length"] += 1
            print("  ↪ 길이 {}자로 규격({}~{}) 밖 — 건너뜀".format(len(text), MIN_CHARS, MAX_CHARS))
            continue
        if norm(title) in seen_titles or norm(text) in seen_texts:
            skipped["duplicate"] += 1
            print("  ↪ 이미 있는 지문 건너뜀: {}".format(title))
            continue

        entry = {
            "id": next_id(today, existing),
            "title": title,
            "theme": theme,
            "text": text,
            "chars": len(text),
            "createdAt": today.strftime("%Y-%m-%d"),
        }
        existing.append(entry)
        seen_titles.add(norm(title))
        seen_texts.add(norm(text))
        saved += 1
        print("  ✅ 저장: [{}] {} ({}자)".format(theme, title, len(text)))

    # 저장할 것이 없어도 파일은 그대로 두고 생존 신호만 남긴다.
    # 「새 지문이 없다」와 「로봇이 죽었다」는 완전히 다른 상황인데, 신호가 없으면 구별할 수 없다.
    if saved:
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    merge_heartbeat({
        "status": "ok",
        "ranAtUtc": today.isoformat(timespec="seconds"),
        "model": model_used,
        "savedThisRun": saved,
        "skipped": skipped,
        "file": file_name,
        "total": len(existing),
        "error": None,
    })
    print("지문 {}편 저장 완료 (누적 {}편 · {})".format(saved, len(existing), file_name))


if __name__ == "__main__":
    main()
