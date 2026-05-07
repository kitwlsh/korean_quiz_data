import os
import json
from google import genai

# 1. 깃허브 금고에서 열쇠(API KEY) 꺼내서 세팅하기
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# 2. 제미나이 AI에게 지시할 내용
prompt = """
한국어 퀴즈 앱에 들어갈 '맞춤법' 객관식 문제 2개와 '사자성어' 주관식 문제 1개를 만들어주세요.
반드시 아래 JSON 배열 형식으로만 대답해주세요. 추가적인 말은 하지 마세요.
[
  {
    "id": 100, // 기존과 겹치지 않게 무작위 높은 숫자
    "type": "MULTIPLE_CHOICE", // 주관식은 SUBJECTIVE
    "category": "맞춤법",
    "question": "다음 중...",
    "options": ["1번", "2번", "3번", "4번"], // 주관식은 null
    "answer": "정답",
    "explanation": "해설",
    "semanticHint": "이 단어는 ~라는 뜻도 있습니다"
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
