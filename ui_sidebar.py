"""사이드바 UI: 향후 기능 추가는 이 파일에서 관리합니다."""
from pathlib import Path
import streamlit as st


NAV_OPTIONS = ["홈", "AI 백서 챗봇", "백서 검색"]


def render_sidebar(*, pdf_ready: bool, key_ready: bool) -> tuple[str, bool]:
    """(선택 메뉴, 목업 모드)를 반환합니다."""
    with st.sidebar:
        with st.container(key="side_brand"):
            st.markdown("### ✳ AIVLE **Insight**")
            st.caption("KT AIVLE SCHOOL · DX LEARNING")

        st.markdown('<div class="side-group-label">WORKSPACE</div>', unsafe_allow_html=True)
        selected = st.radio(
            "서비스 탐색", NAV_OPTIONS,
            key="current_menu", label_visibility="collapsed",
        )

        st.markdown('<div class="side-group-label">COMING SOON</div>', unsafe_allow_html=True)
        st.button("🗓 학습 일정 (준비 중)", disabled=True, use_container_width=True)
        st.button("🧾 FAQ 라이브러리 (준비 중)", disabled=True, use_container_width=True)
        st.button("📊 학습 통계 (준비 중)", disabled=True, use_container_width=True)

        st.divider()
        with st.container(key="side_settings"):
            st.markdown("**작업 환경**")
            preview = st.toggle(
                "목업 모드", value=not (pdf_ready and key_ready),
                help="켜면 API 호출 없이 화면 동작과 배치만 테스트합니다.",
                key="preview_mode",
            )
            if preview:
                st.info("디자인 미리보기 · 실제 백서 검색 없음", icon="🎨")
            elif pdf_ready and key_ready:
                st.success("RAG 구동 준비", icon="✅")
            else:
                st.warning("백서 PDF 또는 API 키 파일 누락", icon="⚠️")

        st.caption("확장 위치: ui_sidebar.py → NAV_OPTIONS 및 render_sidebar")
    return selected, preview
