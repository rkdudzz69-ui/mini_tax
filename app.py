import io
import re
import pandas as pd
import streamlit as st

# (선택) OpenAI SDK
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # 설치 안 되어 있으면 안내만

# ==============================
# 공통 설정
# ==============================
st.set_page_config(page_title="사업자 파일 업로드하기", layout="wide")
st.title("사업자 파일 업로드하기")

# ==============================
# 예시 데이터 (업로드 없을 때 사용)
# ==============================
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""],
}

# ==============================
# 공통 유틸
# ==============================
@st.cache_data(show_spinner=False)
def load_df_from_file(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        content = file.read()
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(content), encoding_errors="ignore")
    else:
        return pd.read_excel(file)

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = out[c].astype(str).str.strip()
    return out

def digits_only(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")

def norm_text(s: str) -> str:
    return (s or "").strip().lower()

# ==============================
# 데이터 로드
# ==============================
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이야. 실제 파일을 올리면 그걸로 분석해!")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 필수 컬럼
required = {"상호", "사업자번호", "대표자", "주민번호", "사업자상태"}
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}")
    st.stop()

# 폐업일자 파싱
if "폐업일자" in df.columns:
    df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
    df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")
else:
    df["폐업일자"] = pd.NA
    df["폐업일자(파싱)"] = pd.NaT

# ==============================
# 사이드바 카테고리
# ==============================
st.sidebar.header("카테고리")
page = st.sidebar.radio(
    "보기 선택",
    ["사업자 조회", "전체 폐업자 조회", "연도별 폐업자 수 통계", "동일 사업자(대표자/주민번호) 내역", "🤖 챗봇"],
    index=0
)

# ==============================
# 1) 사업자 조회 (다중 입력 + 넓은 입력칸)
# ==============================
def render_search(df: pd.DataFrame):
    st.markdown("## 🔎 사업자 조회")
    st.caption("여러 명/여러 조건을 한 번에 검색할 수 있어. 각 입력칸은 상호·대표자·사업자번호·주민번호에 부분 일치로 매칭돼.")

    # 매칭 방식(한 칸 안의 키워드 간)
    match_mode = st.radio("매칭 방식 (각 입력칸에 적용)", ["부분 포함(AND)", "부분 포함(OR)"], horizontal=True)

    # 여러 입력칸(세션 상태)
    if "multi_queries" not in st.session_state:
        st.session_state.multi_queries = [""]  # 시작 1칸

    c_add, c_del, _ = st.columns([1, 1, 6])
    with c_add:
        if st.button("＋ 입력칸 추가", use_container_width=True):
            st.session_state.multi_queries.append("")
    with c_del:
        if st.button("－ 마지막 제거", use_container_width=True) and len(st.session_state.multi_queries) > 1:
            st.session_state.multi_queries.pop()

    # 넓은 입력칸(text_area)
    new_vals = []
    for i, val in enumerate(st.session_state.multi_queries):
        with st.container():
            st.markdown(f"**검색어 #{i+1}**")
            new_vals.append(
                st.text_area(
                    label="",
                    value=val,
                    placeholder="예) 홍길동 111-11-11111 800101-1234567 (공백으로 여러 키워드)",
                    height=50,
                    key=f"query_input_{i}",
                )
            )
    st.session_state.multi_queries = new_vals

    # 작업용 숫자-only 컬럼
    work = df.copy()
    work["_bnum_d"] = work["사업자번호"].apply(digits_only)
    work["_rrn_d"] = work["주민번호"].apply(digits_only)

    # 단일 입력칸에 대한 마스크
    def mask_for_one_query(q: str):
        q = (q or "").strip()
        if not q:
            return pd.Series([False]*len(work), index=work.index)
        terms = [t.strip() for t in q.split() if t.strip()]

        def row_match(row) -> bool:
            hay_text = " ".join([
                norm_text(row.get("상호", "")),
                norm_text(row.get("대표자", "")),
                norm_text(row.get("사업자번호", "")),
                norm_text(row.get("주민번호", "")),
            ])
            hay_digits = " ".join([row["_bnum_d"], row["_rrn_d"]])

            def contains(term: str) -> bool:
                t_txt = term.lower()
                t_dig = digits_only(term)
                ok_txt = (t_txt in hay_text) if t_txt else False
                ok_dig = (bool(t_dig) and t_dig in hay_digits)
                return ok_txt or ok_dig

            checks = [contains(t) for t in terms]
            return all(checks) if match_mode.startswith("부분 포함(AND)") else any(checks)

        return work.apply(row_match, axis=1)

    # 여러 입력칸 결과 OR 결합(합집합)
    masks = [mask_for_one_query(q) for q in st.session_state.multi_queries]
    if any(m.any() for m in masks):
        final_mask = pd.Series(False, index=work.index)
        for m in masks:
            final_mask |= m
        result = work.loc[final_mask].drop(columns=["_bnum_d", "_rrn_d"], errors="ignore")
    else:
        result = work.iloc[0:0]

    # KPI & 결과
    c1, c2 = st.columns(2)
    c1.metric("업로드 행 수", len(df))
    c2.metric("검색 결과 수", len(result))

    if all((q.strip() == "") for q in st.session_state.multi_queries):
        st.info("검색어를 하나 이상 입력해 줘. 여러 명을 찾으려면 ‘＋ 입력칸 추가’를 눌러 각각 입력하면 돼.")
    elif result.empty:
        st.warning("검색 결과가 없어. 철자나 하이픈(-) 유무를 확인해봐!")

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in result.columns]
    st.dataframe(result.reindex(columns=cols), use_container_width=True)

    if not result.empty:
        st.download_button(
            "⬇️ 검색 결과 CSV 다운로드",
            data=result.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
            file_name="사업자_조회_결과.csv",
            mime="text/csv"
        )

# ==============================
# 2) 전체 폐업자 조회
# ==============================
def render_closed_list(df: pd.DataFrame):
    st.markdown("## 📋 전체 폐업자 조회")

    closed = df[df["사업자상태"].astype(str).str.strip() == "폐업"].copy()

    enable_range = st.checkbox("폐업일자 기간으로 필터", value=False)
    if enable_range:
        min_d = pd.to_datetime(closed["폐업일자(파싱)"]).min()
        max_d = pd.to_datetime(closed["폐업일자(파싱)"]).max()
        c1, c2 = st.columns(2)
        start_date = c1.date_input("시작일", value=min_d.date() if pd.notna(min_d) else None)
        end_date = c2.date_input("종료일", value=max_d.date() if pd.notna(max_d) else None)
        if start_date and end_date:
            m = (closed["폐업일자(파싱)"] >= pd.to_datetime(start_date)) & (closed["폐업일자(파싱)"] <= pd.to_datetime(end_date))
            closed = closed[m]

    c1, c2 = st.columns(2)
    c1.metric("폐업자 수", len(closed))
    c2.metric("전체 대비 폐업 비율", f"{(len(closed)/len(df)*100):.1f}%" if len(df) else "0.0%")

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in closed.columns]
    st.dataframe(closed.reindex(columns=cols), use_container_width=True)

    st.download_button(
        "⬇️ 폐업자 목록 CSV 다운로드",
        data=closed.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
        file_name="전체_폐업자_목록.csv",
        mime="text/csv"
    )

# ==============================
# 3) 연도별 폐업자 수 통계
# ==============================
def render_closed_by_year(df: pd.DataFrame):
    st.markdown("## 📈 연도별 폐업자 수 통계")

    closed = df[df["사업자상태"].astype(str).str.strip() == "폐업"].copy()
    closed["폐업연도"] = pd.to_datetime(closed["폐업일자"], errors="coerce").dt.year

    years = sorted([int(y) for y in closed["폐업연도"].dropna().unique()]) if not closed.empty else []
    if years:
        y1, y2 = st.select_slider("연도 범위", options=years, value=(years[0], years[-1]))
        closed = closed[closed["폐업연도"].between(y1, y2)]
    else:
        st.info("폐업 연도 정보가 없습니다.")

    agg = (
        closed["폐업연도"]
        .dropna()
        .value_counts()
        .sort_index()
        .rename_axis("연도")
        .reset_index(name="폐업자 수")
    )

    st.dataframe(agg, use_container_width=True)
    if not agg.empty:
        st.bar_chart(agg.set_index("연도"))

    st.download_button(
        "⬇️ 연도별 통계 CSV 다운로드",
        data=agg.to_csv(index=False).encode("utf-8-sig"),
        file_name="연도별_폐업자_통계.csv",
        mime="text/csv"
    )

# ==============================
# 4) 동일 사업자(대표자/주민번호) 내역
# ==============================
def render_duplicates(df: pd.DataFrame):
    st.markdown("## 👥 동일 사업자(대표자/주민번호) 내역")

    dup_by_owner = df.groupby("대표자", dropna=False).size().reset_index(name="건수")
    dup_by_owner = dup_by_owner[dup_by_owner["건수"] > 1].sort_values("건수", ascending=False)

    dup_by_rrn = df.groupby("주민번호", dropna=False).size().reset_index(name="건수")
    dup_by_rrn = dup_by_rrn[dup_by_rrn["건수"] > 1].sort_values("건수", ascending=False)

    st.subheader("중복 요약")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**대표자 기준 중복**")
        st.dataframe(dup_by_owner, use_container_width=True, height=260)
    with c2:
        st.markdown("**주민번호 기준 중복**")
        st.dataframe(dup_by_rrn, use_container_width=True, height=260)

    st.download_button(
        "⬇️ 대표자 중복 요약 CSV",
        data=dup_by_owner.to_csv(index=False).encode("utf-8-sig"),
        file_name="대표자_중복_요약.csv",
        mime="text/csv"
    )
    st.download_button(
        "⬇️ 주민번호 중복 요약 CSV",
        data=dup_by_rrn.to_csv(index=False).encode("utf-8-sig"),
        file_name="주민번호_중복_요약.csv",
        mime="text/csv"
    )

    st.subheader("상세 조회")
    mode_key = st.radio("조회 기준", ["대표자", "주민번호"], horizontal=True)
    if mode_key == "대표자":
        options = dup_by_owner["대표자"].tolist()
        sel = st.selectbox("대표자 선택", options=options if options else ["(중복 없음)"])
        detail = df[df["대표자"] == sel].copy() if options else df.iloc[0:0]
    else:
        options = dup_by_rrn["주민번호"].tolist()
        sel = st.selectbox("주민번호 선택", options=options if options else ["(중복 없음)"])
        detail = df[df["주민번호"] == sel].copy() if options else df.iloc[0:0]

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in detail.columns]
    st.dataframe(detail.reindex(columns=cols), use_container_width=True)

    if not detail.empty:
        st.download_button(
            "⬇️ 상세 내역 CSV 다운로드",
            data=detail.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"동일사업자_상세_{mode_key}.csv",
            mime="text/csv"
        )

# ==============================
# 5) 🤖 챗봇 (OpenAI)
# ==============================
def render_chatbot():
    st.markdown("## 🤖 챗봇")
    st.caption("OpenAI API 키를 입력하고 아래에서 질문해 봐. (키는 세션에만 저장)")

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "openai_api_key" not in st.session_state:
        st.session_state.openai_api_key = ""

    key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...", value=st.session_state.openai_api_key)
    if key != st.session_state.openai_api_key:
        st.session_state.openai_api_key = key

    model = st.selectbox("모델 선택", ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"], index=0)
    st.divider()

    for msg in st.session_state.chat_messages:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])

    prompt = st.chat_input("무엇이든 물어봐! (예: 특정 대표자의 폐업 연도만 추려줘)")
    if prompt:
        if not st.session_state.openai_api_key:
            st.warning("먼저 OpenAI API 키를 입력해 줘.")
            return
        if OpenAI is None:
            st.error("openai 패키지가 설치되어 있지 않아. requirements.txt에 openai>=1.0.0 추가해 줘.")
            return

        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        try:
            client = OpenAI(api_key=st.session_state.openai_api_key)
            sys_prompt = (
                "너는 세무/사업자 데이터 어시스턴트야. "
                "질문을 명확히 이해하고, 필요하면 표로 간단히 정리해 답해줘."
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sys_prompt}, *st.session_state.chat_messages],
                temperature=0.3,
            )
            answer = resp.choices[0].message.content.strip()
        except Exception as e:
            answer = f"오류가 발생했어: {e}"

        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.markdown(answer)

        chat_df = pd.DataFrame(st.session_state.chat_messages)
        st.download_button(
            "⬇️ 대화 내보내기 (CSV)",
            data=chat_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="chat_history.csv",
            mime="text/csv"
        )

# ==============================
# 라우팅
# ==============================
if page == "사업자 조회":
    render_search(df)
elif page == "전체 폐업자 조회":
    render_closed_list(df)
elif page == "연도별 폐업자 수 통계":
    render_closed_by_year(df)
elif page == "동일 사업자(대표자/주민번호) 내역":
    render_duplicates(df)
else:
    render_chatbot()
