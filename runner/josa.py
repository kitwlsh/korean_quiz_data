# -*- coding: utf-8 -*-
"""OX 문장 틀의 빈칸 `{X}`에 보기를 넣고 **조사를 받침에 맞춘다.**

🔑 Gemini에게는 문항마다 «틀 하나»만 받는다(`ox_template.py`). 보기 4개를 넣는 일은 여기서 한다 —
   그래야 문항 1개 = API 0.04회 정도로 끝나고, 무료 한도로 며칠이면 다 돈다 (K줄달음 doc/03 10-16 Q2).

틀의 조사 표기는 `{X}(이)다` · `{X}(은)는` · `{X}(을)를` · `{X}(으)로` 처럼 괄호형이다.
AI가 괄호 없이 `{X}이다`라고 써 오는 경우가 있어 [normalize]가 괄호형으로 고친다.
"""
import re

SLOT = '{X}'

# 괄호형 표지 → (받침 있을 때, 받침 없을 때). (으)로는 ㄹ받침이면 '로' — fill()에서 따로 본다.
MARKERS = {
    '(이)었다': ('이었다', '였다'),
    '(이)라는': ('이라는', '라는'),
    '(이)라고': ('이라고', '라고'),
    '(이)라': ('이라', '라'),
    '(이)며': ('이며', '며'),
    '(이)고': ('이고', '고'),
    '(이)다': ('이다', '다'),
    '(이)가': ('이', '가'),
    '(은)는': ('은', '는'),
    '(을)를': ('을', '를'),
    '(과)와': ('과', '와'),
    '(으)로': ('으로', '로'),
}

# AI가 써 오는 다른 표기 → 괄호형. 🔴 긴 것부터 맞춘다('이었다'를 '이'로 먼저 자르지 않게).
_ALIASES = [
    ('은(는)', '(은)는'), ('는(은)', '(은)는'),
    ('이(가)', '(이)가'), ('가(이)', '(이)가'),
    ('을(를)', '(을)를'), ('를(을)', '(을)를'),
    ('과(와)', '(과)와'), ('와(과)', '(과)와'),
    ('이었다', '(이)었다'), ('였다', '(이)었다'),
    ('이라는', '(이)라는'), ('라는', '(이)라는'),
    ('이라고', '(이)라고'), ('라고', '(이)라고'),
    ('으로', '(으)로'), ('로', '(으)로'),
    ('이다', '(이)다'), ('다', '(이)다'),
    ('이며', '(이)며'), ('며', '(이)며'),
    ('이고', '(이)고'),
    ('은', '(은)는'), ('는', '(은)는'),
    ('을', '(을)를'), ('를', '(을)를'),
    ('과', '(과)와'), ('와', '(과)와'),
    ('이', '(이)가'), ('가', '(이)가'),
]

# 숫자·로마자는 «읽는 소리»로 받침을 정한다 (LLM=엘엘엠 → 받침 ㅁ, 3.1=삼점일 → ㄹ)
_DIGIT = {'0': 'ㅇ', '1': 'ㄹ', '2': '', '3': 'ㅁ', '4': '', '5': '', '6': 'ㄱ', '7': 'ㄹ', '8': 'ㄹ', '9': ''}
_LATIN = {'L': 'ㄹ', 'M': 'ㅁ', 'N': 'ㄴ', 'R': 'ㄹ'}
_TRAILING = ' ]}」』"\'’”.·…'
_JONG = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ',
         'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']


def final_sound(word):
    """마지막 소리의 받침. '' = 받침 없음 · 'ㄹ' · 'ㄴ' 등 = 그 받침 · None = 모름."""
    w = word.rstrip(_TRAILING)
    # '주식(株式)'처럼 끝 괄호는 벗긴다. '발(을) 구르다'처럼 괄호가 끝이 아니면 그대로
    while w.endswith(')') and '(' in w:
        w = w[:w.rindex('(')].rstrip(_TRAILING)
    if not w:
        return None
    ch = w[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        return _JONG[(code - 0xAC00) % 28]
    if ch in _DIGIT:
        return _DIGIT[ch]
    if ch.isascii() and ch.isalpha():
        return _LATIN.get(ch.upper(), '')
    return None


def normalize(template):
    """`{X}` 바로 뒤 조사를 괄호형으로 고친다. 이미 괄호형이면 그대로."""
    i = template.find(SLOT)
    if i < 0:
        return template
    head, tail = template[:i + len(SLOT)], template[i + len(SLOT):]
    if any(tail.startswith(m) for m in MARKERS):
        return template
    for raw, marker in _ALIASES:
        if tail.startswith(raw):
            return head + marker + tail[len(raw):]
    return template


def fill(template, word):
    """빈칸에 낱말을 넣은 문장. 조사를 정할 수 없으면 None."""
    t = normalize(template)
    i = t.find(SLOT)
    tail = t[i + len(SLOT):]
    for marker, (with_b, without_b) in MARKERS.items():
        if tail.startswith(marker):
            sound = final_sound(word)
            if sound is None:
                return None
            if marker == '(으)로' and sound == 'ㄹ':
                josa = '로'
            else:
                josa = with_b if sound else without_b
            return t[:i] + word + josa + tail[len(marker):]
    return t[:i] + word + tail
