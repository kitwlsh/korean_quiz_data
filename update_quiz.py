import os
import json
import google.generativeai as genai

# 1. 깃허브 금고에서 열쇠(API KEY) 꺼내서 세팅하기
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("오류: GEMINI_API_KEY 환경변수가 설정되지 않았습니다. GitHub Secrets를 확인해 주세요.")
    exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# 2. 제미나이 AI에게 지시할 내용 (프롬프트 고도화)
prompt = """
한국어 퀴즈 앱에 들어갈 고품질의 퀴즈 5개를 만들어주세요. 매번 똑같은 문제가 나오지 않도록 매우 다양하고 교육적인 문제로 구성해주세요.

[문제 구성 (총 5개)]
1. '우리말 겨루기' 카테고리: 맞춤법, 고유어, 사자성어 중 1개 (subCategory에 상세 분류 기입)
2. '트렌드 말하기' 카테고리: 최신 유행어/신조어 1개
3. '상식 백과' 카테고리: 역사, 과학, 시사 상식 중 2개
4. '세계 여행' 카테고리: 국가 수도, 국기, 명소 관련 1개

[필수 조건]
- category는 반드시 '우리말 겨루기', '트렌드 말하기', '상식 백과', '세계 여행' 중 하나를 선택하세요.
- subCategory에는 문제의 세부 분류(예: '맞춤법', '역사', '국가수도')를 적으세요.
- 객관식 문제(MULTIPLE_CHOICE)는 반드시 4개의 보기를 제공하고, 주관식(SUBJECTIVE)은 보기를 null로 하세요.
- answer(정답) 항목은 객관식일 경우 options에 있는 글자와 띄어쓰기 하나까지 완벽하게 일치해야 합니다.
- 절대 answer(정답) 항목이나 options(보기) 항목에 한자(漢字)나 괄호()를 넣지 마세요. 오직 순수 한글로만 작성하세요.
- explanation(해설)에는 왜 정답인지 상세히 적어주세요.
- semanticHint(의미적 힌트)에는 정답을 유추할 수 있는 재미있는 힌트를 적어주세요.
- id 값은 10000에서 99999 사이의 무작위 숫자를 넣어주세요.
- 반드시 아래 JSON 배열 형식으로만 대답해주세요. 추가적인 말이나 마크다운 백틱(`)은 절대 하지 마세요.

[
  {
    "id": 12345,
    "type": "MULTIPLE_CHOICE", 
    "category": "상식 백과",
    "subCategory": "과학",
    "question": "다음 중...",
    "options": ["1번", "2번", "3번", "4번"],
    "answer": "정답",
    "explanation": "해설",
    "semanticHint": "의미적 힌트"
  }
]
"""

# 3. AI에게 물어보기
try:
    print("AI에게 문제를 요청 중입니다...")
    response = model.generate_content(prompt)
    
    # JSON 부분만 추출하기 위한 더 강력한 로직
    raw_text = response.text.strip()
    start_idx = raw_text.find('[')
    end_idx = raw_text.rfind(']') + 1
    
    if start_idx == -1 or end_idx == 0:
        print(f"오류: AI 응답에서 JSON 배열을 찾을 수 없습니다. 응답 내용: {raw_text}")
        exit(1)
        
    json_text = raw_text[start_idx:end_idx]
    new_questions = json.loads(json_text)
    print(f"AI가 {len(new_questions)}개의 문제를 생성했습니다.")

except Exception as e:
    print(f"문제 발생: {str(e)}")
    exit(1)

# 4. 생성된 문제를 카테고리별로 분류하여 저장하기
category_map = {
    "우리말 겨루기": "korean.json",
    "트렌드 말하기": "trend.json",
    "상식 백과": "knowledge.json",
    "세계 여행": "travel.json"
}

def save_question_to_file(file_name, question):
    if os.path.exists(file_name):
        with open(file_name, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
    else:
        data = []
        
    data.append(question)
    
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

for question in new_questions:
    category = question.get("category")
    file_name = category_map.get(category, "quiz_updates.json")
    
    # 1. 카테고리별 파일에 저장
    save_question_to_file(file_name, question)
    
    # 2. 특정 카테고리 파일로 분류된 경우라도 전체 업데이트 파일인 quiz_updates.json에 이중 기록
    if file_name != "quiz_updates.json":
        save_question_to_file("quiz_updates.json", question)

print(f"성공적으로 {len(new_questions)}개의 새로운 퀴즈가 각 카테고리 파일 및 quiz_updates.json에 분산 저장되었습니다!")
