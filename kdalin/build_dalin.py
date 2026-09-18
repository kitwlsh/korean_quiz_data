# -*- coding: utf-8 -*-
"""③달인 도전 문항 생성 — `passages_2026.json` → `dalin_2026.json`

🔴 **`passages_2026.json`을 «읽기만» 한다.** 그 파일은 `update_passages.py`가 만들고
   KDailyUtil의 「빠른 독서 훈련」이 쓰고 있다 — 고치면 그쪽이 깨진다.
   (KDalin/CLAUDE.md · doc/05 §9-4)

🔑 **오류를 AI가 «지어내지» 않는다.** `confusables.PAIRS`에 있는 혼동쌍만 심는다.
   그래서 정답이 언제나 하나이고, 채점이 문자열 비교로 끝난다(doc/06 §1).

🔑 한 지문에서 **난이도별로 여러 벌**을 뽑는다 — 분량이 배로 는다(doc/08 §5-3).

사용:
  NIKL_API_KEY=... python kdalin/build_dalin.py
"""
import io
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import confusables  # noqa: E402
import nikl  # noqa: E402
import passage_source  # noqa: E402
import wordlist  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'passages_2026.json')      # 🔴 읽기 전용
OUT = os.path.join(ROOT, 'dalin_2026.json')

# 🔴 doc/08 §5-3 — 난이도는 「띄어쓰기 오류가 몇 곳인가」로 정한다. 객관적이다.
SPACING_ERRORS = {'easy': 3, 'normal': 5, 'hard': 8}
# 맞춤법 문항 수(지문에서 찾을 수 있는 만큼, 최대)
SPELLING_MAX = {'easy': 3, 'normal': 5, 'hard': 5}
# 보기 수 — hard는 헷갈리는 표기를 하나 더 붙인다
CHOICES = {'easy': 2, 'normal': 2, 'hard': 2}

# 🔑 앱이 한 번에 들고 있을 분량. 오래된 것부터 밀어낸다.
KEEP_ITEMS = 120

# 🔴 하루에 새로 «쓰게» 할 지문 수. 🔑 한 편이 난이도 3벌을 낳으므로 하루 6문항이 는다.
#    Gemini 한도가 짜서(기존 로봇 실측) 욕심내지 않는다.
NEW_PASSAGES_PER_RUN = 2

# ③ 어휘력 — 정답(뜻풀이에 «없는» 낱말) 후보
VOCAB_DISTRACTORS = [
    '고드름', '수레바퀴', '종이배', '쇠망치', '거미줄', '무쇠솥', '연필심', '장작불',
    '물레방아', '대나무', '보름달', '꽹과리',
]
VOCAB_STOPWORDS = {
    '이나', '또는', '있는', '하는', '되는', '따위', '그것', '이것', '저것',
    '여러', '가지', '모든', '어떤', '대한', '위한', '통해', '아니', '아니하',
}
VOCAB_PARTICLES = ('으로서', '으로써', '에서의', '에게서', '으로', '이나', '에서', '에게',
                   '에는', '와의', '과의', '의', '를', '을', '이', '가', '은', '는',
                   '에', '와', '과', '로', '도', '만', '나')
VOCAB_BAD_SUFFIXES = ('도록', '하게', '하여', '으며', '면서', '지만', '거나', '어서')


def spacing_of(text):
    """공백을 뺀 글자열과 경계 배열. 🔴 「공백을 보면 직전 경계를 켠다」로 쓰면 한 칸 밀린다."""
    chars, gaps, pending = [], [], False
    for ch in text:
        if ch == ' ':
            pending = True
            continue
        if chars:
            gaps.append(pending)
        pending = False
        chars.append(ch)
    return ''.join(chars), gaps


def make_initial_spacing(answer_text, wrong_count, rng):
    """정답 경계에서 [wrong_count]곳을 뒤집어 «문제 시작 상태»를 만든다.

    🔑 붙임 오류(띄운 곳을 붙임)와 띄움 오류(붙은 곳을 띄움)를 **섞는다** —
    한쪽만 내면 「전부 붙이면 된다」는 요령이 생긴다.
    🔴 문장부호 뒤 경계는 건드리지 않는다 — 앱이 거기를 잠가 두므로(자동 띄어쓰기)
       뒤집어 봐야 사용자가 고칠 수 없다.
    """
    chars, answer = spacing_of(answer_text)
    punct = {i for i in range(len(answer)) if chars[i] in '.,?!;:'}
    open_gaps = [i for i, v in enumerate(answer) if v and i not in punct]
    closed_gaps = [i for i, v in enumerate(answer) if not v and i not in punct]
    if len(open_gaps) + len(closed_gaps) < wrong_count:
        return None

    want_join = min(len(open_gaps), (wrong_count + 1) // 2)
    want_split = wrong_count - want_join
    if want_split > len(closed_gaps):
        want_split = len(closed_gaps)
        want_join = min(len(open_gaps), wrong_count - want_split)
    if want_join + want_split != wrong_count:
        return None

    flipped = set(rng.sample(open_gaps, want_join)) | set(rng.sample(closed_gaps, want_split))
    return [(not v) if i in flipped else v for i, v in enumerate(answer)]


def build_vocab(key, headword, distractor_from=0):
    """③ 어휘력 — 뜻풀이에 «있는» 낱말 4개 + «없는» 낱말 1개. 못 만들면 None."""
    import re
    got = nikl.definition_of(key, headword)
    if not got:
        return None
    definition = got['definition']

    tokens = []
    for raw in re.findall(r'[가-힣]{2,}', definition):
        t = raw
        for suffix in VOCAB_PARTICLES:
            if t.endswith(suffix) and len(t) - len(suffix) >= 2:
                t = t[: -len(suffix)]
                break
        if len(t) >= 2 and t not in VOCAB_STOPWORDS and not t.endswith(VOCAB_BAD_SUFFIXES):
            tokens.append(t)

    seen, present = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            present.append(t)
    if len(present) < 4:
        return None
    present = sorted(present, key=len, reverse=True)[:4]

    rotated = VOCAB_DISTRACTORS[distractor_from:] + VOCAB_DISTRACTORS[:distractor_from]
    answer = next((w for w in rotated if w not in definition), None)
    if answer is None:
        return None

    return {
        'headword': headword,
        'definition': definition,       # 🔴 원문 그대로
        'link': got['link'],
        'choices': sorted(present + [answer]),
        'answer': answer,
        'note': '',
    }


def build_item(key, passage, level, rng, index):
    """지문 한 편 + 난이도 하나 → 달인 문항 하나. 못 만들면 None."""
    text = ' '.join(passage['text'].split())          # 공백 정규화
    pairs = confusables.usable_pairs(text)[: SPELLING_MAX[level]]
    if len(pairs) < 2:
        return None, '혼동쌍이 %d개뿐' % len(pairs)

    initial = make_initial_spacing(text, SPACING_ERRORS[level], rng)
    if initial is None:
        return None, '띄어쓰기 오류 %d곳을 못 만듦' % SPACING_ERRORS[level]

    spelling = []
    for order, p in enumerate(pairs, start=1):
        got = nikl.definition_of(key, p['head'], p['sense'])
        if not got:
            # 🔴 뜻풀이가 없으면 «해설 없는 문항»이 된다 — 그 문항만 버린다.
            continue
        start = text.index(p['right'])
        spelling.append({
            'order': order,
            'span': [start, start + len(p['right'])],
            'right': p['right'],
            'wrong': p['wrong'],
            'choices': sorted([p['right'], p['wrong']][: CHOICES[level]]),
            'rule': p['rule'],
            'definition': got['definition'],          # 🔴 원문 그대로
            'link': got['link'],
            'note': '',
        })
    if len(spelling) < 2:
        return None, '뜻풀이를 못 구한 문항이 많아 %d개만 남음' % len(spelling)

    # order를 1..n으로 다시 매긴다(중간에 버린 것이 있을 수 있다)
    for i, sp in enumerate(spelling, start=1):
        sp['order'] = i

    item = {
        'id': 'dalin-%s-%s' % (passage['id'], level),
        'sourcePassageId': passage['id'],
        'level': level,
        'title': passage.get('title', ''),
        'answerText': text,
        'initialSpacing': initial,
        'spelling': spelling,
    }

    # ③ 어휘력 — 🔴 **후보를 여럿 시도한다.** 뜻풀이가 짧으면 보기 4개가 안 나온다
    #    (예: '며칠' = 「몇 날.」). 지문의 낱말 → 표제어 풀 순으로 훑는다.
    candidates = [sp['right'] for sp in spelling]
    candidates += [w for w in wordlist.WORDS if len(w) >= 2][:40]
    vocab = None
    for offset, head in enumerate(candidates):
        vocab = build_vocab(key, head, distractor_from=(index * 3 + offset) % 12)
        if vocab is not None:
            break
    if vocab is not None:
        item['vocab'] = vocab
    return item, None


def generated_passages(rng, want, used_ids):
    """🔑 **낱말을 먼저 정하고 지문을 쓰게 한다.**

    🔴 기존 `passages_2026.json`에는 혼동쌍이 한 개도 안 나왔다(2026-09-18 실측) —
    그 파일은 읽기 훈련용 문학 지문이라 맞춤법 함정이 될 낱말이 애초에 안 쓰인다.
    """
    made = []
    pool = [p[0] for p in confusables.PAIRS]
    for i in range(want):
        words = rng.sample(pool, 5)
        theme = passage_source.THEMES[(len(used_ids) + i) % len(passage_source.THEMES)]
        text = passage_source.write_passage(words, theme)
        problems = passage_source.verify(text, words)
        if problems:
            print('  ↪ 지문 %d 버림: %s' % (i + 1, '; '.join(problems)[:120]))
            continue
        pid = 'gen-%s-%d' % (time.strftime('%Y%m%d'), i + 1)
        if pid in used_ids:
            continue
        made.append({'id': pid, 'title': theme, 'text': text})
        print('  ✍ 지문 %s (%d자) — %s' % (pid, len(text), ' · '.join(words)))
    return made


# 🔑 **Gemini 없이 파이프라인을 증명하는** 지문. `--selftest`로만 쓴다.
#    🔴 이것은 시드도 로봇 산출물도 아니다 — 오류 주입·뜻풀이 조회·어휘력 생성이
#    «끝에서 끝까지» 도는지 확인하는 용도다.
SELFTEST_PASSAGE = {
    'id': 'selftest-001',
    'title': '자체 시험',
    'text': (
        '며칠 동안 그는 밤새 뒤척였다. 왠지 마음이 무거웠다. '
        '창밖에는 나뭇잎이 바람에 흔들리고 있었다. '
        '그는 서류를 꼼꼼히 살폈지만 실수는 줄지 않았다. '
        '이번만큼은 반드시 끝내야 한다고 다짐했다.'
    ),
}


def main():
    key = nikl.read_key()
    selftest = '--selftest' in sys.argv
    if selftest:
        passages = [SELFTEST_PASSAGE]
        print('🧪 자체 시험 — Gemini 없이 파이프라인만 확인한다')
    else:
        passages = json.load(io.open(SOURCE, encoding='utf-8'))
        print('지문 %d편을 읽었다 (🔴 읽기 전용)' % len(passages))

    # 🔑 이미 만든 것은 다시 만들지 않는다 — 쿼터를 아끼고 결과가 흔들리지 않는다.
    existing = []
    if os.path.exists(OUT):
        try:
            existing = json.load(io.open(OUT, encoding='utf-8')).get('items', [])
        except ValueError:
            existing = []
    done = {it['id'] for it in existing}

    # 🔑 ① 기존 지문에서 혼동쌍이 나오는 것만 고른다 (API 0회 · 공짜)
    usable_existing = [p for p in passages
                       if len(confusables.usable_pairs(' '.join(p['text'].split()))) >= 2]
    print('기존 지문 중 쓸 수 있는 것: %d편' % len(usable_existing))

    # 🔑 ② 모자라면 «낱말을 주고» 새로 쓰게 한다
    source = list(usable_existing)
    if not selftest and len(source) < NEW_PASSAGES_PER_RUN:
        rng_gen = random.Random(time.strftime('%Y%m%d'))
        source += generated_passages(rng_gen, NEW_PASSAGES_PER_RUN - len(source), done)

    made, skipped = [], []
    for index, passage in enumerate(source):
        for level in ('easy', 'normal', 'hard'):
            item_id = 'dalin-%s-%s' % (passage['id'], level)
            if item_id in done:
                continue
            rng = random.Random('%s|%s' % (passage['id'], level))   # 🔑 결정적
            item, why = build_item(key, passage, level, rng, index)
            if item is None:
                skipped.append('%s: %s' % (item_id, why))
                continue
            made.append(item)
            print('  ✅ %-34s 맞춤법 %d · 띄어쓰기 오류 %d · 어휘력 %s'
                  % (item_id, len(item['spelling']), SPACING_ERRORS[level],
                     '있음' if 'vocab' in item else '없음'))

    items = (existing + made)[-KEEP_ITEMS:]
    if not items:
        print('🔴 만들어진 문항이 없다 — 파일을 쓰지 않는다')
        for s in skipped[:10]:
            print('   -', s)
        return 1

    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'version': 1, 'items': items}, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('\n새로 %d개 · 전체 %d개 → %s' % (len(made), len(items), OUT))
    if skipped:
        print('건너뛴 것 %d개 (처음 5개):' % len(skipped))
        for s in skipped[:5]:
            print('   -', s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
