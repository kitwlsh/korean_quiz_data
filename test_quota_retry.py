# -*- coding: utf-8 -*-
"""로봇 두 스크립트의 «429 처리»를 스텁으로 실제 실행해 검증한다.

돌리는 법:  python test_quota_retry.py     (인터넷·API 키 불필요 · 몇 초)

왜 있나 (2026-09-09)
  08-25에는 429를 «모델을 바꿔도 소용없는 치명적 실패»로 보고 즉시 중단했다.
  2026-09-09 실측(KDailyUtil/doc/AI_KEY_NOTES.md 3-2)에서 그 전제가 뒤집혔다 —
  창은 수십 초이고, 한도는 모델마다 다르다. 그래서 «자고 재시도 -> 그래도 막히면 다음 모델»로 바꿨다.
  🔴 이 파일은 그 새 동작을 못으로 박아 둔다. 되돌리려는 수정이 있으면 여기서 걸린다.

🔬 뮤테이션 시험으로 확인했다(09-09): RETRY_ON_429=0으로 만들면 12건,
   429를 다시 키 오류로 취급하면 16건이 실패한다. 통과만 하는 시험이 아니다.

실제 API 없이 오류 문자열만 흉내내어 분기를 태운다.
🔴 last_run.json을 건드리지 않도록 임시 폴더에서 돈다.
"""
import io
import os
import sys
import json
import tempfile
import types

# 프로젝트 규칙: 절대경로를 쓰지 않는다(폴더를 옮기면 죽는다) - 이 파일이 있는 곳이 저장소다
REPO = os.path.dirname(os.path.abspath(__file__))

Q429 = ("429 You exceeded your current quota ... "
        "Quota exceeded for metric: generativelanguage.googleapis.com/"
        "generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash "
        "Please retry in 3.5s")
Q429_NOHINT = "429 RESOURCE_EXHAUSTED quota exceeded"
KEY_ERR = "403 API key not valid. Please pass a valid API key."
OVERLOAD = "503 The model is overloaded. Please try again later."


def load_module(which):
    """스크립트를 «함수 정의부만» 실행해 이름공간을 얻는다.

    update_quiz.py는 최상위에서 곧바로 API를 부르므로(295줄) 그 앞까지만 exec 한다.
    update_passages.py는 `if __name__` 가드가 있어 통째로 exec 해도 안전하다.
    """
    src = io.open(os.path.join(REPO, which), encoding="utf-8").read()
    if which == "update_quiz.py":
        lines = src.split("\n")
        cut = next(i for i, l in enumerate(lines) if l.startswith("response, MODEL_USED ="))
        src = "\n".join(lines[:cut])
    # google.generativeai는 이 기기에 없다 — 가짜 모듈을 심어 import를 통과시킨다
    fake = types.ModuleType("google.generativeai")
    fake.GenerativeModel = object
    fake.configure = lambda **k: None
    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_pkg.generativeai = fake
    sys.modules["google"] = google_pkg
    sys.modules["google.generativeai"] = fake

    ns = {"__name__": "stub"}
    exec(compile(src, which, "exec"), ns)
    return ns


def run_case(which, plan, label):
    """plan: {모델이름: [동작...]}  동작 = None(성공) 또는 오류 문자열"""
    os.environ["QUIZ_MODEL"] = "modelA"
    os.environ["GEMINI_API_KEY"] = "dummy"  # 스크립트가 최상위에서 키 유무를 검사한다
    ns = load_module(which)

    calls, sleeps = [], []

    class FakeModel(object):
        def __init__(self, name):
            self.name = name

        def generate_content(self, prompt):
            calls.append(self.name)
            seq = plan.get(self.name)
            behavior = seq.pop(0) if seq else None
            if behavior is None:
                return types.SimpleNamespace(text="[]")
            raise Exception(behavior)

    ns["genai"] = types.SimpleNamespace(GenerativeModel=FakeModel, configure=lambda **k: None)
    ns["time"] = types.SimpleNamespace(sleep=lambda s: sleeps.append(s))

    outcome = "ok"
    try:
        ns["generate_with_fallback"]("프롬프트")
    except SystemExit:
        outcome = "fail"

    hb = {}
    if os.path.exists("last_run.json"):
        hb = json.load(io.open("last_run.json", encoding="utf-8"))
        os.remove("last_run.json")

    print("  [{}] 결과={} 호출={} 잠={} quotaWaits={}".format(
        label, outcome, calls, sleeps, ns.get("QUOTA_WAITS")))
    return outcome, calls, sleeps, ns, hb


def main():
    os.chdir(tempfile.mkdtemp(prefix="robotstub_"))
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print("    \u274c " + msg)
        else:
            print("    \u2705 " + msg)

    for which in ("update_quiz.py", "update_passages.py"):
        print("\n===== {} =====".format(which))

        # 1. 429가 두 번 나고 세 번째에 성공 -> 자고 다시 물어 살아난다 (예전 코드는 여기서 죽었다)
        o, c, s, ns, hb = run_case(which, {"modelA": [Q429, Q429, None]}, "429 x2 -> 성공")
        check(o == "ok", "429를 두 번 맞고도 성공한다")
        check(c == ["modelA"] * 3, "같은 모델을 3번 부른다(모델을 성급히 바꾸지 않는다)")
        check(s == [5, 5], "오류가 말한 3.5초 + 여유 2초 = 5초씩 잔다(힌트를 실제로 읽는다)")
        check(ns.get("QUOTA_WAITS") == 2, "생존 신호용 카운터가 2다")

        # 2. 한 모델이 계속 429 -> 다음 모델로 넘어간다 (한도는 모델마다 다르다)
        o, c, s, ns, hb = run_case(
            which, {"modelA": [Q429, Q429, Q429], "gemini-flash-latest": [None]}, "429 계속 -> 모델 교체")
        check(o == "ok", "재시도를 다 쓰면 다음 후보 모델로 넘어가 성공한다")
        check(c == ["modelA"] * 3 + ["gemini-flash-latest"], "재시도 3번 뒤에 비로소 모델을 바꾼다")

        # 3. 키·권한 오류 -> 자지도, 넘어가지도 않고 즉시 멈춘다
        o, c, s, ns, hb = run_case(which, {"modelA": [KEY_ERR]}, "403 키 오류")
        check(o == "fail", "키 오류는 즉시 실패한다")
        check(s == [], "키 오류로는 자지 않는다(자도 낫지 않는다)")
        check(c == ["modelA"], "키 오류로 다른 모델을 태우지 않는다")

        # 4. 503 과부하 -> 자지 않고 곧바로 다음 모델 (08-25에 넣은 동작이 살아 있는지)
        o, c, s, ns, hb = run_case(
            which, {"modelA": [OVERLOAD], "gemini-flash-latest": [None]}, "503 -> 다음 모델")
        check(o == "ok", "503이면 다음 모델로 넘어간다")
        check(s == [], "503으로는 자지 않는다")

        # 5. 모든 모델이 429 -> 실패하되 생존 신호를 남긴다
        o, c, s, ns, hb = run_case(which, {m: [Q429_NOHINT] * 3 for m in (
            "modelA", "gemini-flash-latest", "gemini-3.5-flash", "gemini-3.6-flash")}, "전부 429")
        check(o == "fail", "모든 후보가 429면 실패한다")
        check(len(c) == 12, "후보 4개 x (첫 시도+재시도 2) = 12번 시도한다")
        check(s == [20] * 8, "힌트가 없으면 기본 20초씩 잔다(마지막 후보의 마지막 시도 뒤에는 안 잔다)")
        check(bool(hb), "실패해도 생존 신호 파일을 남긴다")

    print("\n" + ("=" * 60))
    if fails:
        print("실패 {}건:".format(len(fails)))
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("전부 통과")


main()
