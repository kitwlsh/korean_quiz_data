# -*- coding: utf-8 -*-
"""국립국어원 표준국어대사전 API 클라이언트 — K달인 로봇 공용.

🔴 **인증키는 앱에 들어가지 않는다.** 키는 사용자당 1개뿐이라 유출되면 로봇까지 같이 죽는다.
   여기(GitHub Actions Secret `NIKL_API_KEY`)에만 둔다. (KDalin/CLAUDE.md 3번)

🔴 **뜻풀이는 «원문 그대로» 담는다.** 요약·윤문·AI 재작성 금지 —
   표준국어대사전은 CC BY-SA 2.0 KR이고, 고치면 2차적 저작물이 되어
   동일조건변경허락(SA)이 걸린다. 보충 설명은 `note`에 따로 쓴다.
   🔴 **용례(예문)는 담지 않는다** — 출처 있는 용례는 CC 대상이 아니다.

🔑 실측으로 확인한 함정 셋 (KDalin/doc/06 §2-3-2):
   ① `search.do`(JSON)는 표제어당 **첫 번째 뜻만** 준다
   ② 모든 뜻은 `view.do`로만 받을 수 있고 **`view.do`는 XML만** 된다
   ③ **관용구·속담은 검색이 안 되고** 표제어 상세의 `relation_info`에 있다
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEARCH = 'https://stdict.korean.go.kr/api/search.do'
VIEW = 'https://stdict.korean.go.kr/api/view.do'
WORD_URL = 'https://stdict.korean.go.kr/search/searchView.do?word_no=%s'

# 🔑 하루 쿼터는 50,000건이다(KDalin/doc/06 §2-5-2). 로봇 한 번에 수백 건이면 충분히 여유롭지만,
#    연달아 때리면 서버가 막는다 — 호출 사이에 잠깐 쉰다.
THROTTLE_SEC = 0.15


class NiklError(RuntimeError):
    pass


def read_key():
    """Actions Secret → 없으면 로컬 개발용 파일.

    🔴 저장소에 키를 적지 않는다. 로컬에서는 저장소 «밖»에서 읽는다.
    """
    key = os.environ.get('NIKL_API_KEY', '').strip()
    if key:
        return key
    local = r'D:/PERSONAL/20_GitHub/_secrets/KDalin/nikl-openapi.properties'
    if os.path.exists(local):
        for line in io.open(local, encoding='utf-8'):
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1)
                if 'key' in k.lower():
                    return v.strip()
    raise NiklError('NIKL_API_KEY가 없다 (Actions Secret 또는 _secrets 파일)')


def _get(url, params, timeout=20, retries=3):
    """🔑 에러 021(키 일시 중지)이 실재한다 — 한 번 실패로 로봇을 죽이지 않는다."""
    last = None
    for attempt in range(retries):
        try:
            time.sleep(THROTTLE_SEC)
            with urllib.request.urlopen(url + '?' + urllib.parse.urlencode(params),
                                        timeout=timeout) as resp:
                return resp.read().decode('utf-8')
        except (urllib.error.URLError, TimeoutError) as e:  # noqa: PERF203
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise NiklError('요청 실패: %s' % last)


def find(key, word):
    """표제어를 찾아 `target_code`를 돌려준다. 없으면 None."""
    raw = _get(SEARCH, {'key': key, 'q': word, 'req_type': 'json', 'method': 'exact'})
    try:
        hit = json.loads(raw).get('channel', {}).get('item')
    except ValueError:
        return None
    if not hit:
        return None
    if isinstance(hit, dict):
        hit = [hit]
    return hit[0].get('target_code')


def senses(key, word, target_code=None):
    """표제어의 **일반어** 뜻 목록. 🔑 방언·북한어·옛말은 거른다.

    @return [{'definition': 원문, 'pos': 품사}], 그리고 link
    """
    code = target_code or find(key, word)
    if not code:
        return [], ''
    xml = _get(VIEW, {'key': key, 'method': 'target_code', 'q': code})
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], WORD_URL % code
    pos = (root.findtext('.//pos') or '').strip()
    for si in root.iter('sense_info'):
        if (si.findtext('type') or '').strip() != '일반어':
            continue
        definition = (si.findtext('definition') or '').strip()
        if definition:
            out.append({'definition': definition, 'pos': pos})
    return out, WORD_URL % code


# 🔑 초성 힌트로 쓰기에 «너무 긴» 뜻풀이의 기준.
#    방송 힌트를 실측하니 10~20자였다(2026-09-21). 첫 문장이 이보다 길면 다음 뜻을 본다.
SENSE_LIMIT = 60


def best_sense_no(senses, limit=SENSE_LIMIT):
    """뜻이 여럿일 때 **몇 번째를 쓸까**. (2026-09-21 리서치 반영)

    🔑 **한계 안에서 «가장 앞선» 뜻**을 쓴다 — 1번이 대표 뜻이므로 앞쪽을 우선하되,
    너무 길면 다음으로 넘어간다. 「가장 짧은 뜻」을 고르면 「바람 = 매우 빠름을 이르는 말」처럼
    **너무 막연해 못 맞히는** 문항이 나온다(실측).

    🔴 전부 한계를 넘으면 **1번을 쓴다** — 앱이 첫 문장으로 접어 보여준다.
    ⚠️ 「어느 뜻이 «더 유명한가»」는 사전에 없다. 「마당발」처럼 어긋나는 말은
    `wordlist.py`에 뜻 번호를 손으로 적는다.
    """
    for n, s in enumerate(senses, start=1):
        if len(s['definition']) <= limit:
            return n
    return 1


def definition_of(key, word, sense_no=1):
    """한 뜻만. 🔴 몇 번째 뜻인지가 중요하다 — 1번이 늘 맞는 뜻은 아니다.

    예: '며칠'의 1번은 「그달의 몇째 되는 날」이고 「몇 날」은 2번이다.
    그대로 쓰면 **해설이 틀린 말을 한다.**
    """
    got, link = senses(key, word)
    if not got:
        return None
    # 🔑 sense_no가 None이면 «우리가» 고른다(위 best_sense_no). 숫자면 그대로 쓴다.
    if sense_no is None:
        sense_no = best_sense_no(got)
    if sense_no > len(got):
        return None
    return {
        'definition': got[sense_no - 1]['definition'],   # 🔴 원문 그대로
        'pos': got[sense_no - 1]['pos'],
        'link': link,
        'senseCount': len(got),
    }


def relations(key, word, kind):
    """🔑 **관용구·속담은 검색이 안 된다** — 표제어 상세의 `relation_info`에 있다.

    @param kind '관용구' 또는 '속담'
    @return [{'word': 표현, 'definition': 뜻풀이 원문}]
    """
    code = find(key, word)
    if not code:
        return [], ''
    xml = _get(VIEW, {'key': key, 'method': 'target_code', 'q': code})
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], WORD_URL % code
    for ri in root.iter('relation_info'):
        if (ri.findtext('type') or '').strip() != kind:
            continue
        expr = (ri.findtext('word') or '').strip()
        link_code = (ri.findtext('link_target_code') or '').strip()
        if not expr or not link_code:
            continue
        sub = _get(VIEW, {'key': key, 'method': 'target_code', 'q': link_code})
        try:
            sub_root = ET.fromstring(sub)
        except ET.ParseError:
            continue
        definition = ''
        for si in sub_root.iter('sense_info'):
            definition = (si.findtext('definition') or '').strip()
            if definition:
                break
        if definition:
            out.append({'word': expr, 'definition': definition,
                        'link': WORD_URL % link_code})
    return out, WORD_URL % code
