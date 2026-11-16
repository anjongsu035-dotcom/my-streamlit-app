"""AIVLE SCHOOL | AlignIQ 스타일의 데스크톱 우선 Streamlit UI.

사용자 제공 노트북의 원본 RAG는 rag_backend.py에 분리 보존되어 있습니다.
목업 모드에서는 실제 PDF 검색이나 OpenAI 요청을 수행하지 않습니다.
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
    initial_sidebar_state="expanded",
)
st.html(ROOT / "styles.css")

# AIVLE_SIDEBAR_TOGGLE_V1
if "aivle_sidebar_open" not in st.session_state:
    st.session_state.aivle_sidebar_open = True

def toggle_aivle_sidebar():
    st.session_state.aivle_sidebar_open = (
        not st.session_state.aivle_sidebar_open
    )

# 사이드바가 닫힌 경우에만 숨김 스타일 적용
if not st.session_state.aivle_sidebar_open:
    st.html("""
    <style>
    [data-testid="stSidebar"] {
        display: none !important;
    }
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    </style>
    """)


# ── 실제 파일 체크: 노트북 원본의 path 규칙을 해석만 하고 변경하지 않음 ──
def project_path() -> Path:
    try:
        import sys
        if "google.colab" in sys.modules:
            return Path("/content/drive/MyDrive/project04/")
    except Exception:
        pass
    return Path.cwd()


work_dir = project_path()
pdf_ready = (work_dir / PDF_NAME).is_file()
key_ready = (work_dir / "api_key.txt").is_file()

if "dialogue" not in st.session_state:
    st.session_state.dialogue = []
if "latest_result" not in st.session_state:
    st.session_state.latest_result = None
if "history" not in st.session_state:
    st.session_state.history = []
if "active_question" not in st.session_state:
    st.session_state.active_question = None


# 기존 파이프라인은 첫 질문 때만 초기화해 중복 리인덱싱을 줄입니다.
# 주의: 원본 rag_pipeline 내부에는 reset_collection()이 있어 신규 세션에서 재구축합니다.
@st.cache_resource(scope="session", show_spinner=False)
def get_rag():
    from rag_backend import initialize_rag
    return initialize_rag()


def extract_docs(question):
    from rag_backend import retrieve_whitepaper_chunks
    docs = retrieve_whitepaper_chunks(question, k=3)
    return [
        {
            "text": d.page_content,
            "metadata": dict(d.metadata or {}),
        }
        for d in docs
    ]


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
        message = "오른쪽에 **디자인 미리보기 결과**를 표시했어요. (실제 RAG 답변 아님)"
    elif not (pdf_ready and key_ready):
        result = {
            "question": q, "mode": "missing",
            "answer": "**실제 RAG 연결 전입니다.** 프로젝트 폴더에 `AIVLE School 백서.pdf`와 `api_key.txt`를 배치한 뒤 다시 질문하세요.",
            "docs": [],
        }
        message = "백서 파일 또는 API 키 파일이 없어 검색을 실행하지 못했어요."
    else:
        try:
            with st.spinner("백서에서 관련 내용을 찾고 있어요..."):
                rag_chain = get_rag()  # 원본 변수명 및 호출 방식 유지
                answer = rag_chain.invoke({"input": q})
                docs = extract_docs(q)
            result = {"question": q, "mode": "live", "answer": str(answer), "docs": docs}
            message = "백서 기반 답변을 오른쪽 패널에 정리했어요."
        except Exception as exc:
            # 사용자에게 API 키 등 민감 정보가 포함될 수 있는 예외 문자열을 노출하지 않음
            result = {
                "question": q, "mode": "error",
                "answer": "RAG 요청에 실패했습니다. 라이브러리 설치, API 키 형식, 파일 경로와 서버 로그를 확인하세요.",
                "docs": [],
            }
            message = "검색 중 오류가 발생했어요. 서버 로그에서 원인을 확인해 주세요."
            print(f"[RAG error] {type(exc).__name__}")
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
    st.caption("아래는 동일 질문으로 별도 검색한 관련 청크입니다. LLM 답변에 사용된 문단과 반드시 일치하지는 않습니다.")
    for ix, doc in enumerate(docs, start=1):
        meta = doc.get("metadata") or {}
        source_name = Path(str(meta.get("source", "백서 PDF"))).name
        page = meta.get("page")
        # 로더 메타데이터를 그대로 표시 (페이지 번호 기준은 원본 로더에 따름)
        loc = f" · page 메타데이터: {page}" if page is not None else ""
        with st.expander(f"{ix}. {source_name}{loc}", expanded=(ix == 1)):
            st.write(doc["text"])


def render_overview():
    with st.container(key="hero_panel"):
        st.caption("AIVLE SCHOOL / KNOWLEDGE WORKSPACE")
        st.markdown("# 안녕하세요, 에이블러 👋")
        st.write("궁금한 교육 정보를 질문하면 왼쪽에서 대화하고, 오른쪽에서 백서 근거와 답변을 확인할 수 있어요.")

    box1, box2, box3 = st.columns(3, gap="small")
    with box1:
        with st.container(key="metric_mode"):
            st.caption("AI 모드")
            st.markdown("**" + ("UI 시연" if st.session_state.preview_mode else "실제 RAG") + "**")
            st.caption("오픈AI 질문 응답" if not st.session_state.preview_mode else "API 사용 없음")
    with box2:
        with st.container(key="metric_document"):
            st.caption("지식 베이스")
            st.markdown("**AIVLE 백서**")
            st.caption("PDF 인식됨" if pdf_ready else "PDF 연결 대기")
    with box3:
        with st.container(key="metric_retrieval"):
            st.caption("검색 방식")
            st.markdown("**Chroma + RAG**")
            st.caption("원본 코드 그대로 유지")


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
                with st.chat_message("assistant", avatar="✨"):
                    st.write("안녕하세요! 백서에서 궁금한 내용을 물어보세요.")
                    st.caption("현재 UI를 테스트 중이라면 사이드바의 목업 모드를 사용하세요.")
            for item in st.session_state.dialogue:
                with st.chat_message(item["role"], avatar=("✨" if item["role"] == "assistant" else "👤")):
                    st.markdown(item["content"])

        st.chat_input(
            "AIVLE SCHOOL에 대해 질문해 보세요...",
            key="aivle_question_input",
            on_submit=submit_from_chat,
        )
        st.caption("원본 백서 기반 · 목업 모드의 답변은 실제 문서 내용이 아닙니다")


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
            st.markdown("**" + result["question"] + "**")

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
            st.write("기존 `rag_chain.invoke({'input': 질문})`의 응답을 표시합니다.")
            st.write("관련 원문은 동일 질문으로 Chroma에서 **별도로** 조회합니다.")
            st.caption("문서 메타데이터에 출처/페이지가 없으면 임의 생성하지 않습니다.")


def render_guide():
    with st.expander("💡 사용 방법 및 확장 영역", expanded=False):
        st.write("1. 왼쪽 채팅이나 질문 예시를 클릭해 질문하세요.")
        st.write("2. 오른쪽 AI 답변 탭에서 요약을, 원문 탭에서 관련 청크를 확인하세요.")
        st.write("3. 사이드바에서 목업 모드를 끄면 실제 RAG를 사용합니다 (파일 필요).")
        st.info("추가 메뉴는 ui_sidebar.py의 NAV_OPTIONS / render_sidebar에서 구현하면 됩니다.")


# ── 네비게이션 / 실행 ──
selected, _ = render_sidebar(pdf_ready=pdf_ready, key_ready=key_ready)

# 질문 처리: 이벤트 발생 시 상단에서 먼저 처리해 두 패널에 동시에 반영
if st.session_state.active_question:
    pending = st.session_state.active_question
    st.session_state.active_question = None
    submit_question(pending)

with st.container(key="topbar"):
    menu, left, right = st.columns(
        [1.5, 4.5, 2],
        vertical_alignment="center"
    )

    with menu:
        st.button(
            "☰ 메뉴 닫기"
            if st.session_state.aivle_sidebar_open
            else "☰ 메뉴 열기",
            key="sidebar_toggle_button",
            use_container_width=True,
            on_click=toggle_aivle_sidebar,
        )

    with left:
        st.markdown(
            "**✳ AIVLE INSIGHT** &nbsp; / &nbsp; " + selected
        )

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
