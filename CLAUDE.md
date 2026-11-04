# CLAUDE.md

이 저장소에서 Claude 세션이 지킬 것.
폴더 배치·서명키 등 공통 규칙은 `D:/PERSONAL/20_GitHub/README.md` 를 본다.

---

## 📒 K's works - 작업 마무리 기록

전체 프로젝트를 한눈에 보는 자리가 **`D:/PERSONAL/20_GitHub/K's works`** 에 있다.
**작업을 마칠 때** 아래에 해당하는 일이 있었으면 CSV에 **한 줄**만 더한다 - 문서를 새로 쓰지 않는다.

| 생긴 일 | 적을 곳 |
|---|---|
| 미룬 일 · 발견한 문제 | `50_data/todo.csv` 에 한 줄 |
| 그 할 일이 끝남 | `todo.csv` 의 `상태`를 `닫힘`으로 |
| 커밋 메시지로는 설명되지 않는 판단 | `50_data/worklog.csv` 에 한 줄 |
| 프로젝트 상태·진척이 바뀜 (출시 · 착수 · 보관) | `50_data/projects.csv` 의 `상태`·`진행상황` |
| 다른 저장소와 물리는 관계가 생기거나 깨짐 | `50_data/links.csv` |

🔴 **커밋 수 · 최종 작업일 · 태그 수는 적지 마라** - 대시보드가 git에서 직접 읽는다.
🔴 **이 저장소의 문서 내용을 K's works로 복사하지 마라** - 가리키기만 한다. 사본을 두면 갈라진다.

기록한 뒤 대시보드를 다시 만들려면 `K's works/tools/build_dashboard.py`.
자세한 규칙은 `K's works/CLAUDE.md`.
