import os
import json
from google import genai

# 1. 깃허브 금고에서 열쇠(API KEY) 꺼내서 세팅하기
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# 2. 제미나이 AI에게 지시할 내용 (프롬프트 고도화)
prompt = """
한국어 퀴즈 앱에 들어갈 고품질의 우리말 퀴즈 5개를 만들어주세요. 매번 똑같은 문제가 나오지 않도록 매우 다양하고 교육적인 문제로 구성해주세요.

[문제 구성 (총 5개)]
1. '맞춤법 및 띄어쓰기' 객관식 문제 1개 (실생활에서 한국인들이 가장 자주 헷갈리는 것)
2. 'KBS 우리말 겨루기' 스타일의 고난이도 고유어 객관식 문제 1개
3. 아름다운 '순우리말' 뜻 맞추기 주관식 문제 1개
4. '사자성어' 주관식 문제 1개
5. '최신 유행어/신조어' (MZ세대 단어 등) 객관식 문제 1개

[필수 조건]
- 객관식 문제(MULTIPLE_CHOICE)는 반드시 4개의 보기를 제공하고, 주관식(SUBJECTIVE)은 보기를 null로 하세요.
- answer(정답) 항목은 객관식일 경우 options에 있는 글자와 띄어쓰기 하나까지 완벽하게 일치해야 합니다.
- explanation(해설)에는 왜 정답인지 국어사전에 기반하여 상세히 적어주세요.
- semanticHint(의미적 힌트)에는 정답을 유추할 수 있는 재미있는 힌트나, 정답 단어의 또 다른 뜻(다의어)을 적어주세요.
- id 값은 기존 문제들과 겹치지 않도록 10000에서 99999 사이의 무작위 숫자를 넣어주세요.
- 반드시 아래 JSON 배열 형식으로만 대답해주세요. 추가적인 말이나 마크다운 백틱(`)은 절대 하지 마세요.

[
  {
    "id": 12345,
    "type": "MULTIPLE_CHOICE", 
    "category": "신조어", 
    "question": "다음 중...",
    "options": ["1번", "2번", "3번", "4번"],
    "answer": "정답",
    "explanation": "해설",
    "semanticHint": "의미적 힌트"
  }
]
"""

# 3. AI에게 물어보기
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt
)
new_questions = json.loads(response.text.strip('` \njson'))

# 4. 기존 메모장(quiz_updates.json) 열어서 새로운 문제 추가하기
file_path = "quiz_updates.json"
if os.path.exists(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []
else:
    data = []

data.extend(new_questions)

# 5. 메모장에 다시 저장하기
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("성공적으로 새로운 퀴즈 3개가 추가되었습니다!")
