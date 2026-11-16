"""AIVLE School Streamlit front end; RAG logic comes from original notebook.
Original rag_pipeline() creates index in Colab; Streamlit reloads identical chain.
"""
from pathlib import Path
import os
import streamlit as st
from ui_sidebar import render_sidebar

ROOT = Path(__file__).resolve().parent
PDF_NAME = "AIVLE School 백서.pdf"

st.set_page_config(
    page_title="AIVLE Insight | AI 학습 도우미",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",  # Streamlit의 기본 접기/펼치기 화살표 사용
)
st.html(ROOT / "styles.css")

# ── 배포된 Colab Chroma 인덱스를 읽기만 합니다. Streamlit에서 PDF 업로드/재임베딩 금지 ──
INDEX_DIR = ROOT / "chroma_db"
INDEX_READY = (INDEX_DIR / "chroma.sqlite3").is_file()


def openai_key() -> str:
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")) or os.environ.get("OPENAI_API_KEY", "")
    except Exception:
        return os.environ.get("OPENAI_API_KEY", "")


key_ready = bool(openai_key())

for name, value in {
    "dialogue": [],
    "latest_result": None,
    "history": [],
    "active_question": None,
}.items():
    if name not in st.session_state:
        st.session_state[name] = value


@st.cache_resource(show_spinner=False)
def get_rag(index_dir: str, api_key: str):
    os.environ["OPENAI_API_KEY"] = api_key
    from rag_backend import load_existing_rag
    return load_existing_rag(index_dir)


def create_mock_result(question):
    """실제 백서 내용을 만들어내지 않고, 레이아웃용 자리표시자만 반환."""
    return {
        "question": question,
        "mode": "mock",
        "answer": (
            "#### 디자인 미리보기 결과\n\n"
            "이 영역에는 사용자의 질문을 바탕으로 **실제 백서에서 검색한 정보**와 "
            "RAG 답변이 표시됩니다.\n\n"
            "- 핵심 내용과 세부 설명을 보기 쉽게 구성합니다.\n"
            "- 백서에 없는 정보는 추측하지 않는 기존 프롬프트 규칙을 유지합니다.\n"
            "- 원문 탭에는 검색된 문서 청크와 메타데이터를 표시합니다.\n\n"
            "*이 텍스트는 UI 테스트용 자리표시자이며, 실제 백서 답변이 아닙니다.*"
        ),
        "docs": [],
    }


def submit_question(question):
    q = (question or "").strip()
    if not q:
        return
    st.session_state.dialogue.append({"role": "user", "content": q})
    if st.session_state.preview_mode:
        result = create_mock_result(q)
        message = "디자인 시연용 답변입니다. 실제 백서 검색 결과가 아닙니다."
    elif not (INDEX_READY and key_ready):
        result = {
            "question": q, "mode": "missing",
            "answer": "**백서 색인 또는 API 키가 연결되지 않았습니다.** 코랩에서 청킹한 Chroma를 배포하고, Streamlit Secrets를 확인해 주세요.",
            "docs": [],
        }
        message = result["answer"]
    else:
        try:
            with st.spinner("백서에서 관련 문단을 검색하고 답변하는 중..."):
                # Call the user's original RAG LCEL chain, unchanged:
                # rag_chain.invoke({"input": question})
                rag_chain, retriever = get_rag(str(INDEX_DIR), openai_key())
                answer = rag_chain.invoke({"input": q})
                # Separate retrieval only for the right-side source-evidence tab.
                related_docs = retriever.invoke(q)
                docs = [
                    {"text": d.page_content, "metadata": dict(d.metadata or {})}
                    for d in related_docs
                ]
            result = {"question": q, "mode": "live", "answer": str(answer), "docs": docs}
            message = str(answer)
        except Exception as exc:
            result = {
                "question": q, "mode": "error",
                "answer": "백서 검색 중 오류가 발생했습니다. Streamlit Cloud 로그와 색인·API 설정을 확인하세요.",
                "docs": [],
            }
            message = result["answer"]
            print(f"[RAG error] {type(exc).__name__}: {exc}")
    # 실제 RAG의 답변 전체가 채팅 왼쪽에도 보입니다.
    st.session_state.dialogue.append({"role": "assistant", "content": message})
    st.session_state.latest_result = result
    st.session_state.history.insert(0, q)
    st.session_state.history = st.session_state.history[:20]


def enqueue_question(question):
    st.session_state.active_question = question


def submit_from_chat():
    # Streamlit은 on_submit 콜백 호출 시 위젯 값이 session_state에 반영됩니다.
    enqueue_question(st.session_state.get("aivle_question_input", ""))


def render_reference_docs(result):
    docs = result.get("docs", [])
    if result["mode"] == "mock":
        st.info("이 화면은 원문 탭의 배치만 보여줍니다. 실제 백서 청크를 검색한 결과가 아닙니다.")
        with st.container(key="mock_doc"):
            st.markdown("**원문 청크 카드 미리보기**")
            st.caption("파일명 · 페이지 · 검색된 텍스트가 이 위치에 표시됩니다.")
            st.write("실제 검색 모드에서 관련 원문을 확인할 수 있습니다.")
        return
    if not docs:
        st.info("현재 표시할 백서 원문이 없습니다.")
        return
    st.caption("아래 청크는 이번 AI 답변을 만들 때 실제로 사용된 검색 문단입니다.")
    for ix, doc in enumerate(docs, start=1):
        meta = doc.get("metadata") or {}
        source_name = Path(str(meta.get("source", "백서 PDF"))).name
        page = meta.get("page")
        # 로더 메타데이터를 그대로 표시 (페이지 번호 기준은 원본 로더에 따름)
        loc = f" · page 메타데이터: {page}" if page is not None else ""
        with st.expander(f"{ix}. {source_name}{loc}", expanded=(ix == 1)):
            st.write(doc["text"])


def render_overview():
    # 이전의 AI 모드 / AIVLE 백서 / Chroma+RAG 상태 카드 3개 제거
    with st.container(key="hero_panel"):
        st.caption("AIVLE SCHOOL / KNOWLEDGE WORKSPACE")
        st.markdown("# 안녕하세요, 에이블러 👋")
        st.write("왼쪽에서 질문하고, 오른쪽에서 백서 근거와 답변을 확인할 수 있어요.")


def render_chat_panel():
    with st.container(key="chat_panel"):
        head_a, head_b = st.columns([4, 1], vertical_alignment="center")
        with head_a:
            st.markdown("#### ✦ AI 학습 도우미")
            st.caption("질문하고 · 확인하고 · 다시 학습하기")
        with head_b:
            st.caption("● " + ("MOCK" if st.session_state.preview_mode else "LIVE"))

        with st.container(height=480, key="chat_scroll", border=False):
            if not st.session_state.dialogue:
                with st.container(key="chat_assistant_welcome"):
                    st.markdown("**✦ AI 학습 도우미**")
                    st.write("안녕하세요! AIVLE SCHOOL에 관해 궁금한 내용을 입력해 보세요.")
            for index, item in enumerate(st.session_state.dialogue):
                role = item["role"]
                row_key = f"chat_user_{index}" if role == "user" else f"chat_assistant_{index}"
                with st.container(key=row_key):
                    if role == "user":
                        st.caption("나")
                    else:
                        st.caption("✦ AI 학습 도우미")
                    st.markdown(item["content"])

        st.chat_input(
            "AIVLE SCHOOL에 대해 질문해 보세요...",
            key="aivle_question_input",
            on_submit=submit_from_chat,
        )
        st.caption("실제 검색은 Colab에서 구축한 Chroma 인덱스 사용 · 목업은 데모용")


def render_result_panel():
    with st.container(key="result_panel"):
        st.markdown("#### 📖 백서 인사이트")
        st.caption("검색된 정보를 요약하고, 관련 원문을 나란히 살펴보세요.")

        result = st.session_state.latest_result
        if not result:
            with st.container(key="empty_result"):
                st.markdown("### 무엇이 궁금하신가요?")
                st.write("왼쪽 채팅에 질문을 입력하면 이곳에 백서 기반 설명을 보여드려요.")
                st.markdown("**질문 예시**")
                for i, q in enumerate([
                    "DX 컨설턴트는 어떤 일을 하나요?",
                    "AIVLE SCHOOL에서는 어떤 내용을 배우나요?",
                    "선배 교육생들이 추천하는 학습 방법은?",
                ]):
                    st.button(q + "  ↗", key=f"empty_q_{i}", use_container_width=True, on_click=enqueue_question, args=(q,))
            return

        st.caption("검색 질문")
        with st.container(key="question_chip"):
            st.markdown("**" + result["question"].replace("<", "&lt;").replace(">", "&gt;") + "**")

        if result["mode"] == "mock":
            st.warning("디자인 목업 결과 · 실제 백서 검색 아님", icon="🎨")
        elif result["mode"] == "live":
            st.success("실제 RAG 응답", icon="✅")
        else:
            st.warning("RAG 미연결 / 오류", icon="⚠️")

        ans_tab, docs_tab, notes_tab = st.tabs(["✦ AI 답변", "📄 관련 원문", "ℹ️ 검색 정보"])
        with ans_tab:
            with st.container(key="answer_card"):
                st.markdown(result["answer"])
        with docs_tab:
            render_reference_docs(result)
        with notes_tab:
            st.markdown("**현재 검색 방식**")
            st.write("코랩에서 네 `rag_pipeline()`으로 만든 `chroma_db`를 불러옵니다.")
            st.write("관련 원문은 이번 답변의 LLM context에 사용된 청크입니다.")
            st.caption("문서 메타데이터에 출처/페이지가 없으면 임의 생성하지 않습니다.")


def render_guide():
    with st.expander("💡 사용 방법 및 확장 영역", expanded=False):
        st.write("1. 왼쪽 채팅이나 질문 예시를 클릭해 질문하세요.")
        st.write("2. 오른쪽 AI 답변 탭에서 요약을, 원문 탭에서 관련 청크를 확인하세요.")
        st.write("3. 코랩에서 백서 인덱스를 만들고 Streamlit Secrets에 키를 등록한 뒤 목업 모드를 끕니다.")
        st.info("백서 PDF의 청킹·임베딩은 코랩에서 수행합니다. Streamlit은 배포된 Chroma 색인만 읽습니다.")


# ── 네비게이션 / 실행 ──
selected, _ = render_sidebar(index_ready=INDEX_READY, key_ready=key_ready)

# 질문 처리: 이벤트 발생 시 상단에서 먼저 처리해 두 패널에 동시에 반영
if st.session_state.active_question:
    pending = st.session_state.active_question
    st.session_state.active_question = None
    submit_question(pending)

with st.container(key="topbar"):
    left, right = st.columns([5, 2], vertical_alignment="center")
    with left:
        st.markdown("**✳ AIVLE INSIGHT** &nbsp; / &nbsp; " + selected)
    with right:
        st.caption("DX CONSULTANT · AI LEARNING HUB")

render_overview()

if selected == "백서 검색":
    with st.container(key="search_toolbar"):
        with st.form("search_form", clear_on_submit=True):
            search_term = st.text_input("백서에서 검색할 내용을 입력하세요", placeholder="예: DX 취업 준비는 어떻게 하나요?")
            clicked = st.form_submit_button("백서 검색", use_container_width=True)
        if clicked and search_term.strip():
            enqueue_question(search_term)
            st.rerun()

chat_col, results_col = st.columns([0.37, 0.63], gap="medium")
with chat_col:
    render_chat_panel()
with results_col:
    render_result_panel()

render_guide()
