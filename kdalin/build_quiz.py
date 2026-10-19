# -*- coding: utf-8 -*-
"""①초성 · ②일반 문항 생성 → `choseong_2026.json` · `general_2026.json`

🔑 **사전에서 곧바로 생성된다.** 지문 로봇(③달인)을 거치지 않으므로 파이프라인이 다르고,
   그래서 파일도 따로 낸다(KDalin/doc/03 2026-09-17).
🔴 Gemini를 쓰지 않는다 — 국립국어원 API만 쓴다. 한도가 짜지 않고 결과가 흔들리지 않는다.

🔴 **방송 기출을 옮겨 적지 않는다** (CLAUDE.md 1번). 표제어 풀(`wordlist.py`)에서
   뜻풀이를 «조회»해 문항을 만든다.

사용:
  NIKL_API_KEY=... python kdalin/build_quiz.py
"""
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nikl  # noqa: E402
import wordlist  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CHOSEONG = os.path.join(ROOT, 'choseong_2026.json')
OUT_GENERAL = os.path.join(ROOT, 'general_2026.json')

CHO_BASE = 0xAC00
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'

# 🔑 한 번에 새로 만들 개수. 쿼터(하루 50,000건)는 넉넉하지만 실행이 길어지면 실패 반경이 커진다.
# 🔑 평소엔 12개. 🔴 풀을 «몰아서» 채울 때만 환경변수로 올린다 —
#    평소에 크게 잡으면 실행이 길어지고 실패 반경이 커진다.
NEW_PER_RUN = int(os.environ.get('KDALIN_NEW_PER_RUN', '12'))
KEEP_ITEMS = 400

QUESTION_BY_KIND = {
    'definition': '다음 뜻풀이에 해당하는 낱말은?',
    'idiom': '다음 뜻의 관용구는?',
    'proverb': '다음 뜻의 속담은?',
}


def choseong_of(word):
    """🔑 앱은 이 값을 «저장하지 않고» answer에서 유도한다 — 검사용으로만 쓴다."""
    out = []
    for ch in word:
        c = ord(ch)
        out.append(CHO[(c - CHO_BASE) // 588] if CHO_BASE <= c <= 0xD7A3 else ch)
    return ''.join(out)


def pick_balanced(entries, count):
    """🔑 **글자 수를 번갈아** 뽑는다. (2026-09-21 리서치 반영)

    🔴 전에는 목록 앞에서부터 잘랐다(`[:count]`). `WORDS`가 2글자부터 나열돼 있어
    **60문항이 쌓일 때까지 98%가 2글자**였다 — 3·4글자를 목록에 넣어 두고도 차례가 안 왔다.

    🔑 방송은 2~4글자가 고루 나오고 **중심이 3글자**다(KBS 클립 15개 실측).
    """
    by_len = {}
    for word, sense in entries:
        by_len.setdefault(len(word), []).append((word, sense))
    lengths = sorted(by_len)
    out = []
    while len(out) < count and any(by_len[n] for n in lengths):
        for n in lengths:
            if by_len[n]:
                out.append(by_len[n].pop(0))
                if len(out) >= count:
                    break
    return out


def load(path):
    if not os.path.exists(path):
        return {'version': 1, 'items': []}
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except ValueError:
        return {'version': 1, 'items': []}


def save(path, items):
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'version': 1, 'items': items[-KEEP_ITEMS:]}, f,
                  ensure_ascii=False, indent=2)
        f.write('\n')


# ── ① 초성 ──────────────────────────────────────────────────────────────────

def build_choseong(key, entries, pool):
    """🔴 4지선다의 보기는 **초성이 전부 같아야** 한다 — 앱의 `QuizValidation`이 막는다.

    🔑 초성이 같은 낱말을 넷 모으기는 어렵다. 못 모으면 **주관식**으로 낸다 —
    방송의 초성 문제도 주관식에 가깝고, 앱에서는 그게 「어려움」 난이도가 된다.
    """
    made = []
    by_cho = {}
    for w in pool:
        by_cho.setdefault(choseong_of(w), []).append(w)

    for word, sense in entries:
        # 🔑 sense가 None이면 로봇이 고른다(한계 안에서 가장 앞선 뜻).
        got = nikl.definition_of(key, word, sense)
        if not got:
            print('  ↪ 사전에 없다(또는 지정한 뜻이 없다): %s' % word)
            continue
        cho = choseong_of(word)
        same = [w for w in by_cho.get(cho, []) if w != word]
        choices = sorted([word] + same[:3]) if len(same) >= 3 else []
        made.append({
            'id': 'cho-%s' % word,
            'answer': word,
            'definition': got['definition'],       # 🔴 원문 그대로
            'link': got['link'],
            'pos': got['pos'],
            'choices': choices,
            'accepted': [],
            'level': 'normal',
        })
        print('  ✅ %-6s %-5s %s  뜻 %d자%s'
              % (word, cho, '4지선다' if choices else '주관식 ',
                 len(got['definition']), ' (뜻 %s번 지정)' % sense if sense else ''))
    return made


# ── ② 일반 ──────────────────────────────────────────────────────────────────

def definition_distractors(word, prompt, pool):
    """뜻풀이 문항의 오답 보기 3개.

    🔴 전에는 풀 앞에서 3개를 잘랐다(`[:3]`). 140문항 중 139문항의 오답이
    「마음·바람·사람」으로 같아 **보기만 보고 답이 지워졌다** — K줄달음 OX에서는
    「이 셋은 늘 X」로 외워진다(2026-10-19 발견).

    🔑 **글자 수가 같은 낱말**에서 먼저 고른다 — 혼자 긴 보기가 답으로 보이지 않게.
    🔑 시드 = 낱말 → 다시 돌려도 같은 보기가 나온다(앱 캐시·커밋 diff가 흔들리지 않는다).
    🔴 제시문에 나오는 낱말은 보기로 쓰지 않는다 — 뜻풀이 속 낱말이 보기에 있으면 헷갈린다.
    """
    rng = random.Random('gen-def-%s' % word)
    usable = sorted({w for w in pool if w != word and w not in prompt})
    same = [w for w in usable if len(w) == len(word)]
    rng.shuffle(same)
    picked = same[:3]
    if len(picked) < 3:
        rest = [w for w in usable if w not in picked]
        rng.shuffle(rest)
        picked += rest[:3 - len(picked)]
    return picked


def refresh_definition_choices(items, pool):
    """이미 만든 뜻풀이 문항의 보기를 `definition_distractors`로 다시 고른다.

    🔑 사전 API를 다시 부르지 않는다 — 제시문은 그대로, 보기만 바뀐다. 같은 결과가 나오므로
    매번 돌려도 바뀌는 게 없다. 바꾼 개수를 돌려준다.
    """
    changed = 0
    for it in items:
        if it.get('kind') != 'definition':
            continue
        others = definition_distractors(it['answer'], it.get('prompt') or '', pool)
        if len(others) < 3:
            continue
        choices = sorted([it['answer']] + others)
        if choices != it.get('choices'):
            it['choices'] = choices
            changed += 1
    return changed


def build_general_definitions(key, words, pool_defs):
    """뜻풀이 → 낱말. 🔴 제시문에 정답이 그대로 들어 있으면 답이 보인다 → 버린다."""
    made = []
    for word in words:
        got = nikl.definition_of(key, word)
        if not got:
            continue
        prompt = got['definition']
        if word in prompt:
            print('  ↪ 제시문에 정답이 들어 있다: %s' % word)
            continue
        others = definition_distractors(word, prompt, pool_defs)
        if len(others) < 3:
            continue
        made.append({
            'id': 'gen-def-%s' % word,
            'kind': 'definition',
            'question': QUESTION_BY_KIND['definition'],
            'prompt': prompt,                       # 🔴 원문 그대로
            'answer': word,
            'choices': sorted([word] + others),
            'definition': prompt,
            'link': got['link'],
            'rule': '',
            'note': '',
            'level': 'normal',
        })
        print('  ✅ 뜻풀이 %-6s' % word)
    return made


def build_general_relations(key, heads, kind, rng):
    """🔑 관용구·속담은 **검색이 안 된다** — 표제어 상세의 `relation_info`에 있다."""
    made = []
    for head in heads:
        got, _ = nikl.relations(key, head, kind)
        usable = [r for r in got if r['definition'] and r['word']]
        if len(usable) < 4:
            print('  ↪ %s: %s가 %d개뿐' % (head, kind, len(usable)))
            continue
        answer = usable[0]
        distractors = [r['word'] for r in usable[1:4]]
        # 🔴 뜻풀이에 정답 표현이 그대로 들어 있으면 답이 보인다
        if answer['word'] in answer['definition']:
            continue
        made.append({
            'id': 'gen-%s-%s' % ('idiom' if kind == '관용구' else 'proverb', head),
            'kind': 'idiom' if kind == '관용구' else 'proverb',
            'question': QUESTION_BY_KIND['idiom' if kind == '관용구' else 'proverb'],
            'prompt': answer['definition'],          # 🔴 원문 그대로
            'answer': answer['word'],
            'choices': sorted([answer['word']] + distractors),
            'definition': answer['definition'],
            'link': answer['link'],
            'rule': '',
            'note': '',
            'level': 'normal',
        })
        print('  ✅ %s %-4s → %s' % (kind, head, answer['word']))
    return made


def main():
    key = nikl.read_key()
    rng = random.Random(os.environ.get('KDALIN_SEED', ''))

    all_entries = wordlist.entries()
    pool = [w for w, _ in all_entries]

    # ── ① 초성 ──
    cho_feed = load(OUT_CHOSEONG)
    done_cho = {it['id'] for it in cho_feed['items']}
    remaining = [(w, s) for w, s in all_entries if 'cho-%s' % w not in done_cho]
    todo = pick_balanced(remaining, NEW_PER_RUN)
    print('① 초성 — 새로 만들 것 %d개 (글자 수 %s)'
          % (len(todo), '·'.join(str(len(w)) for w, _ in todo)))
    cho_new = build_choseong(key, todo, pool) if todo else []

    # ── ② 일반 ──
    gen_feed = load(OUT_GENERAL)
    done_gen = {it['id'] for it in gen_feed['items']}
    gen_new = []
    refreshed = refresh_definition_choices(gen_feed['items'], pool)
    if refreshed:
        print('② 일반 — 기존 뜻풀이 보기 %d개 다시 고름' % refreshed)

    def_todo = [w for w, _ in pick_balanced(
        [(w, s) for w, s in all_entries if 'gen-def-%s' % w not in done_gen],
        NEW_PER_RUN // 2)]
    if def_todo:
        print('② 일반 — 뜻풀이 %d개' % len(def_todo))
        gen_new += build_general_definitions(key, def_todo, pool)

    for kind, prefix in (('관용구', 'idiom'), ('속담', 'proverb')):
        heads = [h for h in wordlist.RELATION_HEADS
                 if 'gen-%s-%s' % (prefix, h) not in done_gen][: NEW_PER_RUN // 4]
        if heads:
            print('② 일반 — %s %d개' % (kind, len(heads)))
            gen_new += build_general_relations(key, heads, kind, rng)

    if cho_new:
        save(OUT_CHOSEONG, cho_feed['items'] + cho_new)
    if gen_new or refreshed:
        save(OUT_GENERAL, gen_feed['items'] + gen_new)

    print('\n① 초성  새로 %2d개 · 전체 %d개' % (len(cho_new), len(cho_feed['items']) + len(cho_new)))
    print('② 일반  새로 %2d개 · 전체 %d개' % (len(gen_new), len(gen_feed['items']) + len(gen_new)))
    # 🔑 아무것도 못 만들어도 «실패»는 아니다 — 풀을 다 쓴 것일 수 있다.
    return 0


if __name__ == '__main__':
    sys.exit(main())
