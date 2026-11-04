"""Generic CSV dashboard and interactive HTML report; self-contained Streamlit add-on."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from html import escape
from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

MAX_CSV_BYTES = 15 * 1024 * 1024


def _read_csv(upload):
    if upload.size > MAX_CSV_BYTES:
        raise ValueError("CSV 파일은 15MB 이하만 업로드할 수 있습니다.")
    raw = upload.getvalue()
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(BytesIO(raw), encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            pass
        except pd.errors.EmptyDataError:
            raise ValueError("비어 있는 CSV 파일입니다.") from None
        except (pd.errors.ParserError, ValueError) as exc:
            raise ValueError(f"CSV 형식을 확인해주세요: {exc}") from None
    raise ValueError("인코딩을 인식하지 못했습니다. UTF-8 또는 CP949 CSV를 사용해주세요.")


def _recognize_dates(frame):
    dates = {}
    for col in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[col]):
            dates[col] = pd.to_datetime(frame[col], errors="coerce")
            continue
        colname = str(col).lower()
        if not any(k in colname for k in ("date", "날짜", "일자", "일시", "시간", "timestamp")):
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce")
        if len(parsed) and parsed.notna().mean() >= 0.7:
            dates[col] = parsed
    return dates


def _quality_table(frame):
    rows = []
    for col in frame:
        ser = frame[col]
        isnum = pd.api.types.is_numeric_dtype(ser) and not pd.api.types.is_bool_dtype(ser)
        rows.append({
            "컬럼": str(col), "자료형": str(ser.dtype), "결측치": int(ser.isna().sum()),
            "결측률(%)": round(ser.isna().mean() * 100, 2), "고유값 수": int(ser.nunique(dropna=True)),
            "평균(수치형)": round(float(pd.to_numeric(ser, errors="coerce").mean()), 3) if isnum and ser.notna().any() else None,
        })
    return pd.DataFrame(rows)


def _report_html(filename, frame, quality, figures, notes):
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<title>CSV 자동 분석 보고서</title><style>",
         "body{font-family:Arial,'Malgun Gothic',sans-serif;max-width:1150px;margin:35px auto;padding:0 22px;color:#1c2635}",
         "h1,h2{color:#203a61}table{border-collapse:collapse;width:100%;font-size:13px;margin:18px 0}",
         "td,th{border:1px solid #e1e6ee;padding:8px;text-align:left}th{background:#edf4fc}",
         ".meta{color:#6b7280}.block{margin:32px 0}li{line-height:1.75}</style></head><body>",
         "<h1>CSV 데이터 시각화 보고서</h1>",
         f"<p class='meta'>원본 파일: {escape(filename)} | 생성: {escape(now)}</p>",
         f"<p>분석 대상: {len(frame):,}행, {len(frame.columns):,}열 · 업로드된 실제 CSV 기준</p>",
         "<h2>주요 결과 및 유의점</h2><ul>"]
    h.extend(f"<li>{escape(n)}</li>" for n in notes)
    h += ["</ul><h2>컬럼 품질 요약</h2>", quality.to_html(index=False, escape=True, na_rep="-"),
          "<h2>데이터 미리보기 (최대 20행)</h2>", frame.head(20).to_html(index=False, escape=True, na_rep="-"),
          "<h2>시각화</h2>"]
    if not figures:
        h.append("<p>현재 CSV에는 생성 가능한 시각화 조합이 없습니다.</p>")
    for i, (title, fig) in enumerate(figures):
        h.append(f"<section class='block'><h3>{escape(title)}</h3>")
        h.append(pio.to_html(fig, full_html=False, include_plotlyjs=(True if i == 0 else False)))
        h.append("</section>")
    h.append("<p class='meta'>분석은 파일 내 값으로만 수행했으며 결측치는 임의로 0으로 대체하지 않았습니다. 상관관계는 인과관계를 의미하지 않습니다.</p></body></html>")
    return "\n".join(h).encode("utf-8")


def render_csv_report():
    st.title("CSV 업로드 · 데이터 시각화 보고서")
    st.caption("원본 파일을 수정하지 않고 현재 세션에서 분석합니다. OpenAI API로 CSV 내용을 전송하지 않습니다.")
    upload = st.file_uploader("분석할 CSV 파일 업로드", type=["csv"], key="csv_report_file")
    if upload is None:
        st.info("CSV를 업로드하면 자동 데이터 진단과 시각화 보고서를 생성할 수 있습니다.")
        return
    try:
        raw = _read_csv(upload)
    except (ValueError, OSError, UnicodeError) as exc:
        st.error(str(exc))
        return
    if raw.empty or len(raw.columns) == 0:
        st.warning("분석할 행이나 컬럼이 없습니다.")
        return

    frame = raw.copy()
    quality = _quality_table(frame)
    numbers = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_bool_dtype(frame[c])]
    dates = _recognize_dates(frame)
    cats = [c for c in frame.columns if c not in numbers and c not in dates]
    total_missing = int(frame.isna().sum().sum())
    count = max(len(frame) * len(frame.columns), 1)
    notes = [
        f"전체 {len(frame):,}행 / {len(frame.columns)}개 컬럼, 수치형 {len(numbers)}개, 날짜형 후보 {len(dates)}개.",
        f"전체 셀 기준 결측치 {total_missing:,}개 ({total_missing / count * 100:.2f}%).",
        "수치형 통계는 관측된 값만 이용합니다. 다른 항목과 비교 시 집계 방식에 주의하세요.",
    ]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("데이터 행", f"{len(frame):,}")
    m2.metric("컬럼 수", len(frame.columns))
    m3.metric("수치형 컬럼", len(numbers))
    m4.metric("결측 비율", f"{total_missing / count * 100:.1f}%")
    st.subheader("원본 데이터 미리보기")
    st.dataframe(frame.head(100), use_container_width=True, hide_index=True)
    st.caption("원본 데이터는 유지됩니다. 미리보기는 최대 100행입니다.")
    with st.expander("데이터 품질 / 컬럼별 결측치", expanded=False):
        st.dataframe(quality, use_container_width=True, hide_index=True)
        st.download_button("컬럼 품질표 CSV 다운로드", quality.to_csv(index=False).encode("utf-8-sig"),
                           file_name="csv_quality_summary.csv", mime="text/csv", key="csv_quality_export")

    figures = []
    st.subheader("자동 시각화")
    if numbers:
        num = st.selectbox("분포를 확인할 수치형 컬럼", numbers, key="csv_report_hist_num")
        plot_frame = frame[[num]].dropna()
        if not plot_frame.empty:
            fig = px.histogram(plot_frame, x=num, nbins=30, title=f"{num} 분포")
            figures.append((f"{num} 분포", fig))
            st.plotly_chart(fig, use_container_width=True, key="csv_r_hist")
            notes.append(f"{num} 평균: {frame[num].mean():,.2f}, 중앙값: {frame[num].median():,.2f} (결측치 제외).")
    else:
        st.info("수치형 컬럼이 없어 수치 분포 그래프는 생략합니다.")

    if cats and numbers:
        left, right = st.columns(2)
        category = left.selectbox("비교할 범주형 컬럼", cats, key="csv_r_group_col")
        target = right.selectbox("비교할 수치형 컬럼", numbers, key="csv_r_group_metric")
        agg_type = st.radio("범주별 집계", ["합계", "평균", "건수"], horizontal=True, key="csv_r_agg")
        src = frame[[category, target]].dropna(subset=[category])
        if agg_type == "합계":
            grouped = src.groupby(category, dropna=False)[target].sum(min_count=1)
        elif agg_type == "평균":
            grouped = src.groupby(category, dropna=False)[target].mean()
        else:
            grouped = src.groupby(category, dropna=False)[target].count()
        grouped = grouped.dropna().sort_values(ascending=False).head(15).reset_index(name="value")
        if not grouped.empty:
            fig = px.bar(grouped, x=category, y="value", title=f"{category}별 {target} {agg_type} (상위 15개)")
            figures.append((f"{category}별 {target} {agg_type}", fig))
            st.plotly_chart(fig, use_container_width=True, key="csv_r_bar")
            st.caption("범주가 15개를 초과하면 집계값 상위 15개만 표시합니다. 결측 수치는 임의로 0을 채우지 않습니다.")

    if dates and numbers:
        left, right = st.columns(2)
        date_col = left.selectbox("시계열 날짜 컬럼", list(dates), key="csv_r_date_col")
        time_metric = right.selectbox("시계열 수치 컬럼", numbers, key="csv_r_time_metric")
        tmp = pd.DataFrame({"date": dates[date_col], "value": frame[time_metric]}).dropna()
        if not tmp.empty:
            daily = tmp.assign(date=tmp["date"].dt.date).groupby("date", as_index=False)["value"].sum()
            fig = px.line(daily, x="date", y="value", markers=True, title=f"일자별 {time_metric} 합계")
            figures.append((f"일자별 {time_metric} 합계", fig))
            st.plotly_chart(fig, use_container_width=True, key="csv_r_line")
            st.caption("날짜 후보 열을 날짜로 변환 가능한 값만 집계합니다. 날짜별 수치는 합계입니다.")

    if len(numbers) > 1:
        x, y = st.columns(2)
        xcol = x.selectbox("산점도 X축", numbers, index=0, key="csv_r_x")
        ycol = y.selectbox("산점도 Y축", numbers, index=1, key="csv_r_y")
        clean = frame[[xcol, ycol]].dropna()
        if not clean.empty:
            if len(clean) > 3000:
                clean = clean.sample(3000, random_state=42)
                st.caption("산점도 표시 성능을 위해 유효 행 중 3,000개를 무작위 표본으로 표시합니다.")
            fig = px.scatter(clean, x=xcol, y=ycol, opacity=0.6, title=f"{xcol} · {ycol} 관계")
            figures.append((f"{xcol} · {ycol} 산점도", fig))
            st.plotly_chart(fig, use_container_width=True, key="csv_r_scatter")
            st.caption("산점도에서 관계가 보이더라도 인과관계를 의미하지 않습니다.")

    st.subheader("시각화 보고서")
    st.write("보고서에는 데이터 품질표, 원본 미리보기, 선택한 그래프, 실제 수치에 근거한 요약이 들어갑니다.")
    for n in notes:
        st.write("• " + n)
    html_bytes = _report_html(upload.name, frame, quality, figures, notes)
    st.download_button("HTML 시각화 보고서 다운로드", data=html_bytes, file_name="csv_visual_report.html",
                       mime="text/html", key="csv_html_export", type="primary")
    st.caption("HTML 파일은 브라우저에서 열 수 있으며 그래프 스크립트가 파일 안에 포함되어 오프라인에서도 표시됩니다.")
