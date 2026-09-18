# -*- coding: utf-8 -*-
"""③달인 도전용 **지문 공급** — 두 길을 순서대로 시도한다.

🔴 **왜 새로 만드는가 (2026-09-18 실측)**
   처음 설계(KDalin/doc/05 §5)는 「`passages_2026.json`이 이미 있으니 거기에 오류를 심자」였다.
   🔴 **실제로 돌려 보니 혼동쌍이 한 개도 안 나왔다** — 그 파일은 «읽기 훈련용 문학 지문»이라
   맞춤법 함정이 될 낱말('며칠'·'왠지'·'꼼꼼히' 같은 것)이 애초에 안 쓰인다.
   🔑 그래서 **낱말을 먼저 정하고 지문을 쓰게** 한다. doc/05 §4의 「로봇 프롬프트 교체」가
   본래 그 뜻이었다.

   ① 기존 지문에서 혼동쌍이 충분히 나오면 그대로 쓴다 (공짜 · API 0회)
   ② 안 나오면 Gemini에게 **낱말을 주고** 지문을 쓰게 한다

🔴 기존 `passages_2026.json`은 **읽기만** 한다 — KDailyUtil이 쓰고 있다.
"""
import os
import sys
import time

MODEL_CANDIDATES = [
    m for m in [
        os.environ.get('QUIZ_MODEL', '').strip(),   # 🔧 기존 로봇과 «같은» 비상 레버
        'gemini-flash-latest',
        'gemini-3.5-flash',
        'gemini-3.6-flash',
    ] if m
]

RETRY_ON_429 = 2

PROMPT = """너는 한국어 글쓰기 도우미다. 아래 조건으로 짧은 글 한 편을 써라.

[반드시 지킬 것]
1. 다음 낱말을 **철자 그대로**, 각각 **정확히 한 번씩** 자연스럽게 넣어라:
   {words}
2. 분량은 공백 포함 {min_chars}~{max_chars}자.
3. 맞춤법과 띄어쓰기를 **완벽하게** 지켜라. 이 글은 맞춤법 교재의 «정답 원문»으로 쓰인다.
4. 주제는 「{theme}」. 일상적이고 담담한 산문으로 쓴다.
5. 특정 방송 프로그램·퀴즈 프로그램·출연자를 언급하지 마라.
6. 제목이나 설명을 붙이지 말고 **본문만** 출력하라. 따옴표·머리말·꼬리말 금지.

[출력]
본문만."""

THEMES = [
    '비 오는 날의 골목', '오래된 책상', '새벽 시장', '이사하는 날', '낡은 자전거',
    '겨울 아침의 버스', '할머니의 부엌', '도서관의 오후', '첫 출근길', '텃밭의 여름',
]


def _model():
    import google.generativeai as genai
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY가 없다')
    genai.configure(api_key=key)
    return genai


def write_passage(words, theme, min_chars=140, max_chars=220):
    """🔑 낱말을 «주고» 지문을 받는다. 실패하면 None — 로봇이 죽지는 않는다.

    🔴 기존 로봇과 같은 폴백 구조다(모델 후보 · 429 재시도). 한도는 짜고,
    대응은 「자고 다시 묻기 + 모델 바꾸기」다(`update_passages.py` 실측).
    """
    try:
        genai = _model()
    except Exception as e:
        print('  ↪ Gemini를 못 쓴다: %s' % e)
        return None

    prompt = PROMPT.format(
        words=' · '.join(words), theme=theme,
        min_chars=min_chars, max_chars=max_chars,
    )
    for name in MODEL_CANDIDATES:
        for attempt in range(RETRY_ON_429 + 1):
            try:
                resp = genai.GenerativeModel(name).generate_content(prompt)
                text = ' '.join((resp.text or '').split())
                if text:
                    return text
                break
            except Exception as e:                                   # noqa: BLE001
                msg = str(e)
                if '429' in msg or 'quota' in msg.lower():
                    if attempt < RETRY_ON_429:
                        print('  ⏳ %s 한도 초과 — 20초 자고 다시' % name)
                        time.sleep(20)
                        continue
                print('  ↪ %s 실패(%s) — 다음 후보로' % (name, msg[:100]))
                break
    return None


def verify(text, words):
    """🔴 **쓴 글이 조건을 지켰는지 «우리가» 검사한다.** AI 말을 믿지 않는다.

    각 낱말이 정확히 한 번씩 있어야 한다 — 두 번 있으면 `span`이 어느 것을 가리키는지
    알 수 없고, 없으면 문항을 못 만든다.
    """
    problems = []
    if not text:
        return ['본문이 비었다']
    for w in words:
        n = text.count(w)
        if n != 1:
            problems.append("'%s'가 %d번 나온다(1번이어야 한다)" % (w, n))
    if len(text) < 80:
        problems.append('너무 짧다(%d자)' % len(text))
    return problems
