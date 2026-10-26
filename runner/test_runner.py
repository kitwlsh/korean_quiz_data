# -*- coding: utf-8 -*-
"""runner/ 테스트 — 네트워크·키 없이 돈다 (test_quota_retry.py와 같은 «그냥 스크립트» 방식).

사용:
  python runner/test_runner.py
"""
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from josa import fill, final_sound, normalize  # noqa: E402
from ox_template import parse, statements, verify  # noqa: E402

FAILED = []


def eq(got, want, label):
    if got != want:
        FAILED.append(label)
        print('🔴 %s\n   got : %r\n   want: %r' % (label, got, want))
    else:
        print('✅ %s' % label)


# ── 받침 ──
eq(final_sound('목성'), 'ㅇ', '받침 있음')
eq(final_sound('발(을) 구르다'), '', '괄호가 끝이 아니면 그대로')
eq(final_sound('고흐'), '', '받침 없음')
eq(final_sound('사비'), '', '받침 없음 2')
eq(final_sound('하늘'), 'ㄹ', 'ㄹ받침')
eq(final_sound('LLM'), 'ㅁ', '로마자 M=엠')
eq(final_sound('ETF'), '', '로마자 F=에프')
eq(final_sound('3.1 운동'), 'ㅇ', '숫자 섞인 말')
eq(final_sound('2'), '', '숫자 2=이')
eq(final_sound('강동 6주'), '', '숫자 뒤 한글')
eq(final_sound('사건의 지평선'), 'ㄴ', '띄어 쓴 말')
eq(final_sound('주식(株式)'), 'ㄱ', '끝 괄호는 벗긴다')
eq(final_sound('…'), None, '모르는 글자')

# ── 조사 맞추기 ──
eq(fill('태양계에서 가장 큰 행성은 {X}(이)다.', '목성'), '태양계에서 가장 큰 행성은 목성이다.', '(이)다 받침')
eq(fill('태양계에서 가장 큰 행성은 {X}(이)다.', '화성'), '태양계에서 가장 큰 행성은 화성이다.', '(이)다 받침 2')
eq(fill("'별이 빛나는 밤'을 그린 화가는 {X}(이)다.", '고흐'), "'별이 빛나는 밤'을 그린 화가는 고흐다.", '(이)다 받침 없음')
eq(fill('{X}(은)는 온실가스가 아니다.', '산소'), '산소는 온실가스가 아니다.', '(은)는')
eq(fill('{X}(은)는 온실가스가 아니다.', '이산화 탄소'), '이산화 탄소는 온실가스가 아니다.', '(은)는 2')
eq(fill('{X}(은)는 온실가스가 아니다.', '메탄'), '메탄은 온실가스가 아니다.', '(은)는 받침')
eq(fill('수도를 {X}(으)로 옮겼다.', '서울'), '수도를 서울로 옮겼다.', '(으)로 ㄹ받침')
eq(fill('수도를 {X}(으)로 옮겼다.', '사비'), '수도를 사비로 옮겼다.', '(으)로 받침 없음')
eq(fill('수도를 {X}(으)로 옮겼다.', '웅진'), '수도를 웅진으로 옮겼다.', '(으)로 받침')
eq(fill('거대 언어 모델의 약자는 {X}(이)다.', 'LLM'), '거대 언어 모델의 약자는 LLM이다.', '로마자 조사')
eq(fill('{X}(이)가 처음 만들었다.', '장영실'), '장영실이 처음 만들었다.', '(이)가')
eq(fill('정답은 {X}.', '목성'), '정답은 목성.', '조사 없음')
eq(fill('정답은 {X}(이)다.', '…'), None, '조사를 못 정하면 None')

# ── AI가 괄호 없이 써 온 조사 ──
eq(normalize('가장 큰 행성은 {X}이다.'), '가장 큰 행성은 {X}(이)다.', '이다 → (이)다')
eq(normalize('가장 큰 행성은 {X}다.'), '가장 큰 행성은 {X}(이)다.', '다 → (이)다')
eq(normalize('{X}은(는) 온실가스가 아니다.'), '{X}(은)는 온실가스가 아니다.', '은(는) → (은)는')
eq(normalize('{X}는 온실가스가 아니다.'), '{X}(은)는 온실가스가 아니다.', '는 → (은)는')
eq(normalize('{X}이었다.'), '{X}(이)었다.', '이었다(긴 것 먼저)')
eq(normalize('수도를 {X}로 옮겼다.'), '수도를 {X}(으)로 옮겼다.', '로 → (으)로')
eq(normalize('{X}(이)다.'), '{X}(이)다.', '이미 괄호형')
eq(normalize('{X} 에서 열렸다.'), '{X} 에서 열렸다.', '띄어 쓴 뒤는 그대로')

# ── 틀 검사 ──
OPTS = ['지구', '화성', '목성', '토성']
eq(verify('태양계에서 가장 큰 행성은 {X}(이)다.', OPTS, '목성'), [], '좋은 틀')
eq(len(verify('태양계에서 가장 큰 행성은 목성이다.', OPTS, '목성')) > 0, True, '빈칸 없음')
eq(len(verify('{X}보다 목성이 크다: {X}', OPTS, '목성')) > 0, True, '빈칸 두 개')
eq(any('답이 샌다' in x for x in verify('목성은 {X}(이)다.', OPTS, '목성')), True, '정답이 틀에 들어 있다')
eq(any('물음표' in x for x in verify('가장 큰 행성은 {X}?', OPTS, '목성')), True, '물음표')
eq(verify('', OPTS, '목성'), ['틀이 비었다'], '빈 틀')
eq(verify(None, OPTS, '목성'), ['틀이 비었다'], 'None 틀')
eq(any('틀 표기가 남았다' in x for x in verify('{X}(은)는 물(을)를 품은 행성이다.', OPTS, '목성')), True, '딴 자리 표지')

st = statements('태양계에서 가장 큰 행성은 {X}(이)다.', OPTS, '목성')
eq(st[0], {'text': '태양계에서 가장 큰 행성은 목성이다.', 'answer': 'O'}, '정답 문장이 맨 앞')
eq([s['answer'] for s in st], ['O', 'X', 'X', 'X'], 'O 1 + X 3')

# ── 응답 파싱 ──
eq(parse('```json\n[{"id": "q-1", "template": "{X}(이)다."}]\n```')['q-1']['template'], '{X}(이)다.', '코드블록 섞인 응답')
eq(parse('미안합니다'), {}, 'JSON 없음')
eq(parse('[{"id": "q-1",]'), {}, '깨진 JSON')
eq(list(parse('[{"id": 30001, "template": "x"}]')), ['30001'], '숫자 id는 문자열로')

print()
if FAILED:
    print('🔴 실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('✅ 전부 통과')
