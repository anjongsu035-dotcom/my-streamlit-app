"""AIVLE Insight sidebar. The PDF and embedding index are managed in Colab."""
import streamlit as st

NAV_OPTIONS = ["홈", "AI 백서 챗봇", "백서 검색"]


def render_sidebar(*, index_ready: bool, key_ready: bool) -> tuple[str, bool]:
    with st.sidebar:
        with st.container(key="side_brand"):
            st.markdown("### ✳ AIVLE **Insight**")
            st.caption("KT AIVLE SCHOOL · DX LEARNING")

        st.markdown('<div class="side-group-label">WORKSPACE</div>', unsafe_allow_html=True)
        selected = st.radio("서비스 탐색", NAV_OPTIONS,
                            key="current_menu", label_visibility="collapsed")

        st.markdown('<div class="side-group-label">COMING SOON</div>', unsafe_allow_html=True)
        st.button("🗓 학습 일정 (준비 중)", disabled=True, use_container_width=True)
        st.button("🧾 FAQ 라이브러리 (준비 중)", disabled=True, use_container_width=True)
        st.button("📊 학습 통계 (준비 중)", disabled=True, use_container_width=True)

        st.divider()
        with st.container(key="side_settings"):
            st.markdown("**작업 환경**")
            preview = st.toggle(
                "목업 모드", value=not (index_ready and key_ready),
                help="켜면 API 호출 없이 디자인만 확인합니다.",
                key="preview_mode",
            )
            if preview:
                st.info("디자인 시연 중 · 실제 백서 답변 아님", icon="🎨")
            elif index_ready and key_ready:
                st.success("백서 검색 준비 완료", icon="✅")
            elif not index_ready:
                st.warning("코랩에서 만든 Chroma 인덱스가 아직 배포되지 않았습니다.")
            else:
                st.warning("Streamlit Cloud Secrets의 OPENAI_API_KEY 설정 필요")

        st.caption("백서 PDF는 코랩에서 청킹·임베딩합니다. 이 화면에서는 PDF를 업로드하지 않습니다.")
    return selected, preview
