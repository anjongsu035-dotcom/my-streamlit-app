"""User-authored marketing features adapted to run inside existing team Streamlit app.
The separate Streamlit page setup and independent navigation were intentionally removed.
"""
import os
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from openai import OpenAI

COMPETITOR_COLS = [
    "date", "brand", "platform", "content_type",
    "views", "likes", "comments", "shares", "saves",
]
INFLUENCER_COLS = [
    "name", "handle", "platform", "category", "followers",
    "avg_views", "avg_likes", "avg_comments", "fee_krw",
    "brand_fit", "profile_url",
]

SYSTEM_PROMPT = """당신은 지시자의 업무를 지원하는 AI 마케팅 비서 '에이블'입니다.
지시된 목적과 제공된 데이터에 근거해 한국어로 간결하고 실무적으로 답하세요.
확인된 수치/사실, 계산 결과, AI의 해석/추측, 실행 제안을 구분하세요.
제공되지 않은 수치, 경쟁사 성과, 인플루언서 정보, URL, 출처를 절대 만들어내지 마세요.
현재 시스템에는 실시간 웹 검색 도구가 연결되어 있지 않습니다.
외부 검색을 하지 않았으면서 '조사 완료'라고 말하지 마세요.
SNS 결과물은 지시자가 검토하기 위한 초안입니다. 자동 게시나 자동 메일 발송을 하지 마세요.
"""


def api_client():
    """로컬 환경 변수 또는 Streamlit Secrets에서 키를 가져옵니다."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        try:
            key = st.secrets.get("OPENAI_API_KEY")
        except Exception:
            key = None
    if not key:
        st.error("OpenAI API 키가 없습니다. Streamlit Secrets에 OPENAI_API_KEY를 등록하세요.")
        return None
    return OpenAI(api_key=key)


def ai_request(task_text):
    client = api_client()
    if client is None:
        return None
    try:
        with st.spinner("AI가 업무를 처리하는 중입니다..."):
            response = client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task_text},
                ],
            )
        return response.output_text or "AI 응답이 비어 있습니다."
    except Exception:
        st.error("AI 요청이 실패했습니다. API 키, 모델 접근 권한 및 사용 한도를 확인하세요.")
        return None


def read_csv(upload):
    if upload is None:
        return None
    raw = upload.getvalue()
    for encoding in ["utf-8-sig", "cp949"]:
        try:
            return pd.read_csv(BytesIO(raw), encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            st.error(f"CSV를 읽을 수 없습니다: {exc}")
            return None
    st.error("CSV 인코딩을 확인해주세요(UTF-8 또는 CP949).")
    return None


def numeric(col):
    return pd.to_numeric(col, errors="coerce").where(lambda s: s >= 0)


def prepare_competitors(raw):
    missing = sorted(set(COMPETITOR_COLS) - set(raw.columns))
    if missing:
        st.error(f"경쟁사 CSV에 필요한 열이 없습니다: {', '.join(missing)}")
        return None
    df = raw.copy()
    for c in ["views", "likes", "comments", "shares", "saves"]:
        df[c] = numeric(df[c])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["brand"] = df["brand"].fillna("미상").astype(str)
    df["platform"] = df["platform"].fillna("미상").astype(str)
    # 일부 항목이 미수집이면 0으로 치환하지 않습니다.
    df["interactions"] = df[["likes", "comments", "shares", "saves"]].sum(
        axis=1, min_count=4
    )
    df["view_reaction_rate_pct"] = (
        df["interactions"] / df["views"].where(df["views"] > 0) * 100
    )
    return df


def competitor_summary(df):
    # 전체 게시물 수와 '반응률 계산 가능' 게시물 수를 분리합니다.
    grouped = df.groupby("brand").agg(
        posts=("brand", "size"),
        total_views=("views", lambda s: s.sum(min_count=1)),
    )
    eligible = df.loc[(df["views"] > 0) & df["interactions"].notna()]
    valid_group = eligible.groupby("brand").agg(
        comparable_views=("views", "sum"),
        comparable_reactions=("interactions", "sum"),
        posts_with_complete_metrics=("brand", "size"),
    )
    summary = grouped.join(valid_group, how="left").reset_index()
    summary["view_reaction_rate_pct"] = (
        summary["comparable_reactions"] / summary["comparable_views"] * 100
    )
    return summary.sort_values("total_views", ascending=False, na_position="last")


def prepare_influencers(raw):
    missing = sorted(set(INFLUENCER_COLS) - set(raw.columns))
    if missing:
        st.error(f"인플루언서 CSV에 필요한 열이 없습니다: {', '.join(missing)}")
        return None
    df = raw.copy()
    for c in ["followers", "avg_views", "avg_likes", "avg_comments", "fee_krw"]:
        df[c] = numeric(df[c])
    df["brand_fit"] = pd.to_numeric(df["brand_fit"], errors="coerce")
    df.loc[~df["brand_fit"].between(1, 5), "brand_fit"] = float("nan")
    # 조회율(팔로워 대비 평균 조회수), 평균 조회수 대비 반응률
    df["view_rate_pct"] = df["avg_views"] / df["followers"].where(df["followers"] > 0) * 100
    valid_reactions = df[["avg_likes", "avg_comments"]].sum(axis=1, min_count=2)
    df["reaction_rate_pct"] = valid_reactions / df["avg_views"].where(df["avg_views"] > 0) * 100
    df["cost_per_1000_views_krw"] = (
        df["fee_krw"] / df["avg_views"].where(df["avg_views"] > 0) * 1000
    )
    return df


def remember(title, answer):
    st.session_state.marketing_history.insert(
        0,
        {
            "time": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M"),
            "title": title,
            "answer": answer,
        },
    )


def show_download(text, name, label="결과 TXT 내려받기"):
    st.download_button(label, text.encode("utf-8-sig"), file_name=name, mime="text/plain")


def demo_competitor():
    return pd.DataFrame([
        ["2026-10-01", "가상브랜드 A", "인스타그램", "릴스", 12000, 500, 30, 40, 20],
        ["2026-10-02", "가상브랜드 A", "인스타그램", "이미지", 6500, 170, 12, 8, 10],
        ["2026-10-03", "가상브랜드 B", "인스타그램", "릴스", 21000, 760, 58, 80, 55],
        ["2026-10-04", "가상브랜드 B", "인스타그램", "이미지", 4800, 190, 15, 9, 12],
        ["2026-10-05", "가상브랜드 C", "인스타그램", "릴스", 17500, 690, 32, 35, 45],
        ["2026-10-06", "가상브랜드 C", "인스타그램", "이미지", 7200, 220, 18, 16, 8],
    ], columns=COMPETITOR_COLS)


def demo_influencer():
    return pd.DataFrame([
        ["가상 크리에이터 A", "@creator_a", "인스타그램", "뷰티", 70000, 23000, 800, 44, 800000, 4, ""],
        ["가상 크리에이터 B", "@creator_b", "인스타그램", "뷰티", 30000, 15000, 480, 26, 400000, 5, ""],
        ["가상 크리에이터 C", "@creator_c", "유튜브", "라이프스타일", 120000, 41000, 1000, 70, 1400000, 3, ""],
    ], columns=INFLUENCER_COLS)




def render_marketing_page(page):
    # ----------------------------------------------------------------------
    # 2. 화면과 데이터 로딩
    # ----------------------------------------------------------------------
    if "marketing_history" not in st.session_state:
        st.session_state.marketing_history = []
    if "sns_draft" not in st.session_state:
        st.session_state.sns_draft = ""
    if "competitor_ai" not in st.session_state:
        st.session_state.competitor_ai = ""
    if "influencer_ai" not in st.session_state:
        st.session_state.influencer_ai = ""

    with st.sidebar:
        st.divider()
        st.subheader("마케팅 데이터 등록")
        st.download_button(
            "경쟁사 CSV 양식 다운로드",
            pd.DataFrame(columns=COMPETITOR_COLS).to_csv(index=False).encode("utf-8-sig"),
            file_name="competitor_template.csv", mime="text/csv",
        )
        competitor_upload = st.file_uploader("경쟁사 게시물 CSV", type="csv", key="comp_csv")
        st.download_button(
            "인플루언서 CSV 양식 다운로드",
            pd.DataFrame(columns=INFLUENCER_COLS).to_csv(index=False).encode("utf-8-sig"),
            file_name="influencer_template.csv", mime="text/csv",
        )
        influencer_upload = st.file_uploader("인플루언서 후보 CSV", type="csv", key="infl_csv")
        use_demo = st.checkbox("가상 예시 데이터로 체험하기", value=False)
        if use_demo:
            st.info("가상 데이터입니다. 실제 업체나 사람의 조사 결과가 아닙니다.")
        st.caption("수집 출처·기준 날짜·조회수 정의를 확인한 뒤 업로드하세요.")

    comp_raw = read_csv(competitor_upload)
    infl_raw = read_csv(influencer_upload)
    if comp_raw is None and use_demo:
        comp_raw = demo_competitor()
    if infl_raw is None and use_demo:
        infl_raw = demo_influencer()
    comp = prepare_competitors(comp_raw) if comp_raw is not None else None
    infl = prepare_influencers(infl_raw) if infl_raw is not None else None

    st.title(f"🤖 에이블 | {page}")
    if use_demo:
        st.warning("업로드되지 않은 데이터 항목은 가상 예시로 대체되었습니다. 실제 성과와 혼동하지 마세요.")


    # ----------------------------------------------------------------------
    # 3. 통합 대시보드
    # ----------------------------------------------------------------------
    if page == "m_dashboard":
        st.write("입력한 데이터에서 계산된 지표를 한눈에 확인합니다.")
        if comp is None and infl is None:
            st.info("왼쪽에서 CSV를 업로드하거나 '가상 예시 데이터'를 선택하세요.")
        else:
            metrics = st.columns(4)
            metrics[0].metric("경쟁사 게시물", f"{len(comp):,}개" if comp is not None else "자료 없음")
            metrics[1].metric("총 조회수", f"{comp['views'].sum(min_count=1):,.0f}" if comp is not None and comp["views"].notna().any() else "자료 없음")
            valid = comp.loc[(comp["views"] > 0) & comp["interactions"].notna()] if comp is not None else pd.DataFrame()
            rate = valid["interactions"].sum() / valid["views"].sum() * 100 if not valid.empty else None
            metrics[2].metric("조회 대비 반응률", f"{rate:.2f}%" if rate is not None else "계산 불가")
            metrics[3].metric("인플루언서 후보", f"{len(infl):,}명" if infl is not None else "자료 없음")
            if comp is not None:
                st.subheader("브랜드별 조회수")
                overall = competitor_summary(comp)
                available = overall.dropna(subset=["total_views"])
                if not available.empty:
                    st.bar_chart(available.set_index("brand")["total_views"])
                st.caption("반응률은 좋아요+댓글+공유+저장이 모두 수집된 게시물만 계산합니다.")
            if infl is not None:
                st.subheader("후보자별 평균 조회수")
                if infl["avg_views"].notna().any():
                    st.bar_chart(infl.dropna(subset=["avg_views"]).set_index("name")["avg_views"])


    # ----------------------------------------------------------------------
    # 4. 경쟁사 분석
    # ----------------------------------------------------------------------
    elif page == "m_competitor":
        st.write("업로드된 게시물 실적을 집계하고 AI가 분석 보고서를 작성합니다.")
        if comp is None:
            st.info("왼쪽에 경쟁사 CSV를 올려주세요.")
        else:
            platform = st.multiselect("플랫폼 필터", sorted(comp["platform"].unique().tolist()), default=sorted(comp["platform"].unique().tolist()))
            chosen = comp.loc[comp["platform"].isin(platform)]
            if chosen.empty:
                st.info("선택된 플랫폼의 데이터가 없습니다.")
            else:
                summary = competitor_summary(chosen)
                st.dataframe(summary, use_container_width=True, hide_index=True)
                st.subheader("브랜드별 조회수 비교")
                viewable = summary.dropna(subset=["total_views"])
                if not viewable.empty:
                    st.bar_chart(viewable.set_index("brand")["total_views"])
                st.subheader("브랜드별 조회 대비 반응률 (%)")
                measurable = summary.dropna(subset=["view_reaction_rate_pct"])
                if not measurable.empty:
                    st.bar_chart(measurable.set_index("brand")["view_reaction_rate_pct"])
                else:
                    st.info("조회수와 네 종류의 반응 지표가 모두 있는 게시물이 필요합니다.")
                st.caption("조회 대비 반응률 = (좋아요+댓글+공유+저장) / 조회수 × 100. 플랫폼별 집계 방식이 다를 수 있습니다.")
                st.download_button(
                    "분석 요약 CSV 다운로드",
                    summary.to_csv(index=False).encode("utf-8-sig"),
                    "competitor_summary.csv", "text/csv",
                )
                if st.button("AI 경쟁사 분석 보고서 생성", type="primary"):
                    payload = summary.round(2).to_csv(index=False)
                    task = (
                        "다음 경쟁사 실적 표로 1) 핵심 발견 3가지 2) 상위 콘텐츠 전략 3) 우리 브랜드 실행 제안 "
                        "4) 데이터 한계점을 작성하세요. 표에 없는 사실은 추정하지 마세요.\n\n" + payload
                    )
                    result = ai_request(task)
                    if result is not None:
                        st.session_state.competitor_ai = result
                        remember("경쟁사 분석", result)
                if st.session_state.competitor_ai:
                    st.markdown(st.session_state.competitor_ai)
                    show_download(st.session_state.competitor_ai, "competitor_report.txt")


    # ----------------------------------------------------------------------
    # 5. SNS 콘텐츠 초안
    # ----------------------------------------------------------------------
    elif page == "m_sns":
        st.write("홍보 목적을 입력하고 검토용 콘텐츠 초안을 생성합니다. 자동 게시하지 않습니다.")
        with st.form("sns_form"):
            brand = st.text_input("브랜드명", placeholder="예: 우리 브랜드")
            product = st.text_input("제품·서비스명", placeholder="예: 신제품 단백질 음료")
            left, right = st.columns(2)
            platform = left.selectbox("게시 플랫폼", ["인스타그램", "유튜브 쇼츠", "틱톡", "블로그", "기타"])
            purpose = right.selectbox("홍보 목표", ["인지도 확대", "참여 유도", "웹사이트 방문", "구매 전환"])
            audience = st.text_input("타깃 고객", placeholder="예: 운동을 시작한 20~30대")
            tone = st.selectbox("글의 분위기", ["친근한", "전문적인", "재치 있는", "프리미엄"])
            facts = st.text_area("검증된 제품 장점·필수 문구·주의사항", placeholder="확인된 사실만 입력하세요")
            use_comp_context = st.checkbox("업로드한 경쟁사 집계 결과 참고", value=True)
            generate = st.form_submit_button("SNS 홍보 초안 3개 만들기", type="primary")
        if generate:
            if not brand.strip() or not product.strip():
                st.warning("브랜드명과 제품명을 입력하세요.")
            else:
                context = ""
                if use_comp_context and comp is not None:
                    context = "\n경쟁사 집계(참고용):\n" + competitor_summary(comp).round(2).to_csv(index=False)
                task = f"""다음 조건으로 SNS 마케팅 홍보 초안 3개를 서로 다르게 작성하세요.
    브랜드: {brand}
    제품: {product}
    플랫폼: {platform}
    목표: {purpose}
    타깃: {audience}
    톤: {tone}
    확인된 제품 정보: {facts}
    {context}
    각 초안에 1) 한 줄 훅 2) 본문 또는 영상 구성 3) CTA 4) 해시태그 5) 승인 전 검토할 사항을 작성하세요.
    확인되지 않은 효능, 판매량, 할인율, 소비자 평가를 만들어내지 마세요.
    """
                result = ai_request(task)
                if result is not None:
                    st.session_state.sns_draft = result
                    remember("SNS 홍보 초안", result)
        if st.session_state.sns_draft:
            st.markdown(st.session_state.sns_draft)
            show_download(st.session_state.sns_draft, "sns_drafts.txt")


    # ----------------------------------------------------------------------
    # 6. 인플루언서 후보 비교
    # ----------------------------------------------------------------------
    elif page == "m_influencer":
        st.write("등록된 후보를 정량 비교하고, 사람이 최종 검토할 우선순위를 제안합니다.")
        if infl is None:
            st.info("왼쪽에 인플루언서 후보 CSV를 올려주세요. 이 버전은 실시간 웹 검색을 하지 않습니다.")
        else:
            min_fit = st.slider("최소 브랜드 적합도(담당자 평가: 1~5점)", 1, 5, 3)
            selected = infl.loc[infl["brand_fit"] >= min_fit].copy()
            if selected.empty:
                st.warning("조건에 맞는 후보가 없습니다. 적합도 기준을 조정해주세요.")
            else:
                selected = selected.sort_values(["brand_fit", "cost_per_1000_views_krw"], ascending=[False, True], na_position="last")
                cols = ["name", "handle", "platform", "category", "followers", "avg_views", "view_rate_pct", "reaction_rate_pct", "cost_per_1000_views_krw", "brand_fit", "profile_url"]
                st.dataframe(selected[cols].round(2), use_container_width=True, hide_index=True)
                st.caption("조회율 = 평균조회수/팔로워 ×100, 반응률 = (평균 좋아요+댓글)/평균조회수 ×100, 예상 조회 1,000회당 비용 = 제안비/평균조회수 ×1,000(원).")
                st.caption("브랜드 적합도는 사람이 평가한 점수입니다. 조회 1,000회당 비용은 예상 비교용이며 실제 광고 도달·성과를 보장하지 않습니다.")
                st.download_button("후보 목록 CSV 다운로드", selected.to_csv(index=False).encode("utf-8-sig"), "influencers_scored.csv", "text/csv")
                if st.button("AI 후보 검토 보고서 생성", type="primary"):
                    task = (
                        "다음은 이미 수집한 인플루언서 후보 데이터입니다. 외부 신규 후보를 조사한 것처럼 쓰지 마세요. "
                        "브랜드 적합도, 예상 조회 1,000회당 비용, 반응률을 함께 고려해 우선 검토 후보 3명(없으면 있는 만큼)을 "
                        "추천하고 장단점, 확인해야 할 위험·실제 고객층 확인 사항을 적으세요.\n\n"
                        + selected.round(2).to_csv(index=False)
                    )
                    result = ai_request(task)
                    if result is not None:
                        st.session_state.influencer_ai = result
                        remember("인플루언서 후보 평가", result)
                if st.session_state.influencer_ai:
                    st.markdown(st.session_state.influencer_ai)
                    show_download(st.session_state.influencer_ai, "influencer_report.txt")


    # ----------------------------------------------------------------------
    # 7. 업무 기록
    # ----------------------------------------------------------------------
    elif page == "m_history":
        st.write("현재 브라우저 세션에서 생성된 결과입니다. 장기 저장을 하려면 DB가 추가로 필요합니다.")
        if not st.session_state.marketing_history:
            st.info("아직 수행한 AI 업무가 없습니다.")
        for item in st.session_state.marketing_history:
            with st.expander(f"{item['time']} · {item['title']}"):
                st.markdown(item["answer"])
        if st.session_state.marketing_history:
            combined = "\n\n---\n\n".join(
                f"{i['time']} {i['title']}\n\n{i['answer']}" for i in st.session_state.marketing_history
            )
            show_download(combined, "able_history.txt", "업무 기록 전체 다운로드")
