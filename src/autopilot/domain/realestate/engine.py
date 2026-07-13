"""Real-estate view builder.

KOREA: rate stance from the BANK OF KOREA (operator-set, since the watcher may lack BOK
headlines) — NOT the Fed. Concrete 행정동/단지 (with search deep-links), 광역철도 plans,
청약 watch, and a 부동산-specific news feed split out from the general news.
US: a DIVERSE pool of markets rotated DAILY (Maryland is just one example), with a
simplified archive of past days' picks. Bold-but-disclaimed; accuracy prioritized."""

from __future__ import annotations

from autopilot.domain.realestate.schemas import (
    ArchiveEntry,
    KrListing,
    RealEstateInstrument,
    RealEstateStance,
    RealEstateTopic,
    RealEstateView,
    UsMarket,
)
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal

# real-estate news keywords (to split RE news out of the general feed)
RE_NEWS_KEYWORDS = (
    "부동산",
    "아파트",
    "분양",
    "청약",
    "재건축",
    "재개발",
    "전세",
    "월세",
    "주택",
    "집값",
    "분양가",
    "GTX",
    "철도",
    "신도시",
    "토지거래",
    "종부세",
    "양도세",
    "취득세",
    "재산세",
    "LTV",
    "DSR",
    "대출",
    "임대",
    "공시가",
    "mortgage",
    "housing",
    "REIT",
    "home",
)

_KR_TOPICS = (
    RealEstateTopic(
        title="핵심지 · 핵심 아파트",
        body="금리·전세·정책에 가장 민감하며 하락기 방어·상승기 선도. 입지(직주근접·학군·교통)가 가격을 좌우합니다.",
        bullets=(
            "강남 3구(강남·서초·송파)·용산·마용성(마포·용산·성동)이 상급지 대장",
            "전세가율·갭(매매-전세) 추이가 단기 수급의 핵심 지표",
            "토지거래허가구역 지정 여부로 거래 난이도가 크게 달라짐",
        ),
    ),
    RealEstateTopic(
        title="신도시 · 3기 신도시",
        body="공급 물량·교통망(특히 GTX) 연계가 인근 시세를 좌우. 입주기 전세 약세에 유의.",
        bullets=(
            "3기: 남양주왕숙·하남교산·고양창릉·부천대장·인천계양",
            "사전청약→본청약→입주 일정과 분담금 점검",
        ),
    ),
    RealEstateTopic(
        title="재개발 · 재건축",
        body="안전진단→조합설립→사업시행→관리처분→이주·철거→준공. 단계가 오를수록 불확실성↓·가격↑.",
        bullets=(
            "재초환·분양가상한제가 사업성에 직접 영향",
            "관리처분인가 전후가 변동성·기회의 분기점",
        ),
    ),
    RealEstateTopic(
        title="경매 · 공매",
        body="시세 대비 할인 매수 기회이나 권리분석 실패 시 손실. 명도까지 비용·시간 고려.",
        bullets=("말소기준권리·대항력 임차인 분석", "감정가·최저가·유찰로 경쟁강도 파악"),
    ),
)

_KR_RAIL = (
    RealEstateTopic(
        title="GTX (광역급행철도) — 부동산 최대 변수",
        body="수도권 광역철도는 역세권 시세를 재편하는 핵심 변수입니다. 노선별 진행 단계와 지연 여부를 반드시 확인하세요.",
        bullets=(
            "GTX-A(운정~동탄): 일부 구간 개통/단계 개통 — 삼성역 등 일부 정거장 공사 지연 이슈 점검",
            "GTX-B(인천대입구~마석): 착공 단계 — 공정·예산 따라 개통 지연 가능",
            "GTX-C(덕정~수원): 착공/공사 — 노선·정거장(왕십리·인덕원 등) 변동·지연 점검",
            "GTX-D/E/F: 노선 계획 단계 — 확정 전 기대가 선반영되면 변동성↑(계획 변경 리스크)",
        ),
    ),
    RealEstateTopic(
        title="도시철도 · 광역 교통 (착공/지연)",
        body="신안산선·월곶판교선·위례신사선 등 광역·도시철도와 BRT는 주변 단지 수요를 끌어올립니다.",
        bullets=(
            "착공·개통 임박 노선 인접 단지는 선반영 vs 추가 상승 여부를 구분",
            "예타·재정 문제로 '지연·재검토' 뉴스가 나오면 기대가 빠르게 되돌려질 수 있음",
            "개통 시점(D-day)과 실제 통행시간 단축 효과를 분리해서 평가",
        ),
    ),
    RealEstateTopic(
        title="서부선 경전철 (새절~서울대입구) — 서북·서남 관통",
        body="6호선 새절역에서 2호선 서울대입구역까지 15.6km·16개역. 2024년 말 민자적격성 심의(민투심)를 통과해 16년 만에 본궤도에 올랐고 2026년 착공이 목표입니다. 새절~서울대입구 약 27분(현재 37~42분).",
        bullets=(
            "은평(새절)·서대문·동작·관악(서울대입구)을 한 줄로 — 은평 신사동/관악 신림 정비사업과 수혜축이 겹침",
            "아직 착공 전이라 역세권 선반영이 덜 됨 → 확정 임박 구간을 미리 선점하는 전략이 유효(공격형)",
            "민자사업 특성상 실시협약·실시설계에서 일정이 지연될 수 있음 — 확정 전 기대 선반영 리스크 점검",
        ),
    ),
    RealEstateTopic(
        title="고양은평선 + 신사고개역 — 은평 직접 수혜 (신사고개역은 추진 중)",
        body="고양 식사동~은평 새절을 잇는 광역철도. 2024년 12월 기본계획이 승인됐고 2026년 착공·2031년 개통이 목표입니다. 은평 입장의 핵심 변수는 '신사고개역' 신설 여부입니다.",
        bullets=(
            "신사고개역: 기본계획에서는 일단 제외(탈락) → 은평구가 재추진 중. 2026년 2월까지 사전타당성 보완용역을 마치고 기본계획 변경(역 추가)을 대광위에 요청할 계획",
            "신사고개역이 확정되면 신사동(편백·산새마을) 일대가 서부선 새절 + 고양은평선 더블 역세권으로 직접 수혜",
            "역 신설은 아직 미확정 = 호재 선반영 후 무산되면 되돌림 → '확정 전 저가 매수, 확정 시 차익'은 전형적 고위험·고수익 베팅",
        ),
    ),
    RealEstateTopic(
        title="동부선·동북권 경전철 (계획·검토 단계)",
        body="서울 동북권 교통 보강을 위한 경전철 구상(동부선 등)은 아직 계획·검토 단계로 노선·역사·재원이 확정 전입니다.",
        bullets=(
            "계획 단계 노선은 기대만으로 가격이 먼저 움직였다가 변경·지연 뉴스에 빠르게 되돌려짐",
            "확정 노선(착공·개통 임박) 대비 변동성이 가장 큼 — 소액·분산으로 접근",
            "이미 공사 중인 동북선(왕십리~상계)과는 진행 단계가 다르니 혼동 주의",
        ),
    ),
)

# Concrete 행정동/단지 — reference watch-list with reliable search deep-links (not live listings).
_KR_LISTINGS = (
    KrListing(
        area="강남구 대치동",
        complexes=("은마", "래미안대치팰리스", "대치동부센트레빌"),
        note="학군·재건축 기대. 토지거래허가구역 — 실거주 요건 확인.",
        query="대치동 아파트 시세",
    ),
    KrListing(
        area="강남구 개포동",
        complexes=("디에이치아너힐즈", "개포자이프레지던스", "래미안블레스티지"),
        note="재건축 신축 벨트. 신축 선호 강함.",
        query="개포동 아파트 시세",
    ),
    KrListing(
        area="서초구 반포동",
        complexes=("아크로리버파크", "래미안원베일리", "반포자이"),
        note="한강·신축 프리미엄 최상급지.",
        query="반포동 아파트 시세",
    ),
    KrListing(
        area="송파구 잠실동",
        complexes=("엘스", "리센츠", "트리지움", "잠실주공5단지"),
        note="대단지·교통(2·8호선). 주공5단지는 재건축 기대.",
        query="잠실동 아파트 시세",
    ),
    KrListing(
        area="용산구 이촌·한남",
        complexes=("한가람", "LG한강자이", "한남더힐", "나인원한남"),
        note="용산정비창·국제업무지구 호재. 초고가 단지 포함.",
        query="용산구 이촌동 아파트 시세",
    ),
    KrListing(
        area="마포구 아현·공덕",
        complexes=("마포래미안푸르지오", "마포프레스티지자이", "공덕자이"),
        note="도심 직주근접(마용성). 실수요 두터움.",
        query="마포구 아현동 아파트 시세",
    ),
    KrListing(
        area="성동구 성수·왕십리",
        complexes=("트리마제", "갤러리아포레", "센트라스"),
        note="성수 준공업·지식산업·한강 호재. 신흥 상급지.",
        query="성동구 성수동 아파트 시세",
    ),
)

# 재개발·재건축 pool — concrete, well-known sites with search deep-links. Daily-rotated.
_KR_REDEV_POOL = (
    KrListing(
        area="압구정 재건축",
        complexes=("현대(특별계획3)", "한양", "미성"),
        note="강남 최상급 재건축 대장. 신속통합기획 진행 — 사업 단계·기부채납 점검.",
        query="압구정 재건축",
    ),
    KrListing(
        area="여의도 재건축",
        complexes=("시범", "삼부", "한양", "광장"),
        note="금융중심 재건축 클러스터. 용적률·층수 완화 기대.",
        query="여의도 재건축",
    ),
    KrListing(
        area="목동 신시가지",
        complexes=("1~14단지",),
        note="학군+대단지 재건축. 안전진단·종상향 이슈가 변수.",
        query="목동 신시가지 재건축",
    ),
    KrListing(
        area="잠실 주공5단지",
        complexes=("주공5단지",),
        note="잠실 핵심 재건축. 70층 계획·정비계획 단계.",
        query="잠실 주공5단지 재건축",
    ),
    KrListing(
        area="대치 은마",
        complexes=("은마",),
        note="대표 재건축 상징. 조합·인허가 진행 속도가 관건.",
        query="대치 은마 재건축",
    ),
    KrListing(
        area="1기 신도시 선도지구",
        complexes=("분당", "일산", "평촌", "산본", "중동"),
        note="노후계획도시 특별법 선도지구 — 정부 추진 가속(각광).",
        query="1기 신도시 재건축 선도지구",
    ),
    KrListing(
        area="한남뉴타운",
        complexes=("한남2구역", "한남3구역", "한남4·5구역"),
        note="서울 최대어 재개발. 한남3 착공·이주 단계로 시장 주목.",
        query="한남뉴타운 재개발",
    ),
    KrListing(
        area="성수전략정비구역",
        complexes=("1~4지구",),
        note="한강변 초고층 재개발. 성수 호재로 각광.",
        query="성수전략정비구역 재개발",
    ),
    KrListing(
        area="노량진뉴타운",
        complexes=("1~8구역",),
        note="도심 접근성 우수 재개발. 구역별 진행 차이 확인.",
        query="노량진뉴타운 재개발",
    ),
    KrListing(
        area="이문·휘경뉴타운",
        complexes=("이문1·3·4", "휘경3"),
        note="동북권 대단지 일반분양 활발(각광).",
        query="이문 휘경 재개발",
    ),
    KrListing(
        area="흑석뉴타운",
        complexes=("흑석9·11구역",),
        note="한강·동작 입지 재개발. 분양 성과 양호.",
        query="흑석뉴타운 재개발",
    ),
    KrListing(
        area="광명뉴타운",
        complexes=("광명1·2·4·5R", "철산·하안"),
        note="수도권 대규모 재개발. 신안산선·GT-B 연계 기대.",
        query="광명뉴타운 재개발",
    ),
)


def select_kr_redev(ordinal: int, n: int = 5) -> tuple[KrListing, ...]:
    """Daily-rotated highlight of redevelopment/reconstruction sites."""
    size = len(_KR_REDEV_POOL)
    start = ordinal % size
    return tuple(_KR_REDEV_POOL[(start + i) % size] for i in range(min(n, size)))


# 항상 상단에 고정 노출하는 관심 구역 — 매일 로테이션과 별개(필수 관심지역 + 저평가 성장 베팅).
_KR_REDEV_PINNED = (
    KrListing(
        area="⭐ 은평 신사동 편백·산새마을 (필수 관심)",
        complexes=("신사동 200번지 일대(편백마을)", "237번지 일대(산새마을)"),
        note=(
            "편백·산새마을 통합 신속통합기획. 2025년 6월 정비구역 지정·정비계획이 가결됐고 최고 33층·약 2,896세대로 재개발 예정. "
            "서부선 새절역 + 고양은평선 신사고개역(추진 중) 호재축의 한가운데. 정비구역 지정 단계라 초기 진입 여지가 남은 공격형 후보."
        ),
        query="은평구 신사동 편백마을 재개발",
    ),
    KrListing(
        area="⭐ 관악 신림6구역 (신림뉴타운 인접)",
        complexes=("신림동 일대(삼성산 자락)",),
        note=(
            "신속통합기획 → 2026년 정비구역 지정 고시. 최고 28층·957가구(임대 189) 규모. 삼성산 숲세권 + 신림초 초품아 입지. "
            "신림선(개통) 수혜. 저층 노후주거지가 대단지로 바뀌는 초기~중기 단계라 단계 상승 차익 여력이 큼."
        ),
        query="신림6구역 재개발",
    ),
    KrListing(
        area="⭐ 관악 신림5구역 (신림6과 연계)",
        complexes=("신림동 412 일대",),
        note=(
            "구역면적 약 16만㎡의 대형 구역. 인접한 신림6구역과 지형·생활권을 공유해 연계 개발 추진. "
            "신림뉴타운(2025년 사업시행인가)과 함께 신림동 재개발 시계가 빨라지는 흐름의 한 축."
        ),
        query="신림5구역 재개발",
    ),
    KrListing(
        area="은평 수색·증산뉴타운 + 갈현1구역 (저평가 성장)",
        complexes=("수색4·6·7·13", "증산2·5", "갈현1구역"),
        note=(
            "DMC 배후 은평권 정비 벨트. 신사동과 같은 은평 생활권이라 서부선·고양은평선 교통개선을 함께 누림. "
            "강남권 대비 저가라 진입장벽이 낮은 성장 베팅 — 구역별 진행 단계 차이를 확인하고 선별."
        ),
        query="수색증산뉴타운 갈현1구역 재개발",
    ),
    KrListing(
        area="동북권 장위·상계뉴타운 (저평가 대단지)",
        complexes=("장위뉴타운(성북)", "상계뉴타운(노원)"),
        note=(
            "서울 동북권 대규모 뉴타운. 구역별 진행 차가 크지만 가격이 상대적으로 낮아, 단계 상승(조합설립→관리처분)에 따른 "
            "시세 레버리지가 큼. 동북권 경전철 계획과 맞물리는 장기 성장축."
        ),
        query="장위뉴타운 상계뉴타운 재개발",
    ),
)


# 리스크 선호형(공격적) 투자 전략 — '리스크를 감수하고 수익을 노리는' 투자자 관점. 면책은 _NOTES 참조.
_KR_STRATEGY = (
    RealEstateTopic(
        title="🔥 공격형 핵심 전략 — 한 줄 요약",
        body=(
            "이미 확정된 호재를 비싸게 사는 대신, '곧 확정될' 호재를 미리 싸게 사서 단계 상승의 차익을 노립니다. "
            "정비사업 초기 + 교통 호재 착공 전 = 가장 싸고, 가장 변동성 큰 구간."
        ),
        bullets=(
            "정비사업은 단계(조합설립→사업시행→관리처분)가 오를수록 불확실성↓·가격↑ → 초기에 들어갈수록 싸지만 무산·지연 리스크를 감수",
            "교통 호재(서부선·고양은평선)는 착공·개통이 임박할수록 선반영 → 확정 전에 선점해야 차익이 큼",
            "강남 대장은 안전하지만 비쌈 → 같은 자금으로 은평·관악·동북권 저평가 구역에 들어가 '성장 여력'에 베팅",
        ),
    ),
    RealEstateTopic(
        title="① 정비사업 초기 진입 (조합설립 전후)",
        body="정비구역 지정·조합설립 직전후가 가격은 낮고 상승 여력은 가장 큰 구간입니다.",
        bullets=(
            "편백마을·신림5·6처럼 '정비구역 지정~조합' 단계 구역을 노림 — 관리처분으로 갈수록 권리가액·프리미엄이 뜀",
            "신속통합기획·모아타운은 행정 절차가 빨라 단계 상승 속도가 빠름(시간 리스크↓)",
            "리스크: 초기일수록 사업 무산·정체·분담금 증가 가능 — 구역별 사업성(비례율)·조합 갈등을 반드시 점검",
        ),
    ),
    RealEstateTopic(
        title="② 교통 호재 선점 (착공 전 역세권)",
        body="서부선·고양은평선·신사고개역처럼 '추진 중'인 노선의 예정 역세권을 착공 전에 선점합니다.",
        bullets=(
            "편백·산새마을 = 서부선 새절 + 고양은평선 신사고개역(추진 중)의 더블 역세권 후보 — 두 호재의 교차점",
            "신사고개역은 아직 미확정 → 확정 시 큰 점프, 무산 시 되돌림. 전형적 고위험·고수익 이벤트 베팅",
            "리스크: 민자·예타·재정 변수로 노선 일정이 흔들림 → 한 구역에 몰빵 대신 호재축을 분산",
        ),
    ),
    RealEstateTopic(
        title="③ 레버리지·실행 규칙 (공격하되 살아남기)",
        body="고수익을 노리되, 금리·규제 리스크에 깨지지 않도록 한도와 출구를 미리 정합니다.",
        bullets=(
            "전세 레버리지(갭)·대출은 한국은행 금리·DSR가 조이면 가장 먼저 압박 — 감당 가능한 한도 안에서만",
            "입주권·분양권 프리미엄은 정책·금리에 민감하게 출렁임 → 진입가·목표가·손절선을 숫자로 미리 정함",
            "분산: 필수 관심(편백) + 연계(신림5·6) + 저평가(수색증산·장위) 등 단계가 다른 구역을 섞어 한 곳의 무산 리스크를 흡수",
        ),
    ),
)


_KR_SUBSCRIPTIONS = (
    RealEstateTopic(
        title="청약 — 지금 주목할 권역 (청약홈에서 실시간 확인)",
        body="구체 단지·일정은 청약홈(applyhome.co.kr)에서 매일 확인하세요. 아래는 분양 대기/주목 권역입니다.",
        bullets=(
            "동탄2·평택 고덕국제신도시: 공급 지속, GTX·삼성 반도체 벨트 수혜 기대",
            "광명뉴타운(철산·하안)·이문/휘경 재개발: 도심 접근성 좋은 정비사업 일반분양",
            "3기 신도시 본청약(왕숙·교산·창릉 등): 사전청약 후 본청약 일정 확인",
            "과천지식정보타운·위례: 입지 대비 분양가 메리트 점검",
            "전략: 분양가상한제 단지는 시세차익 크나 실거주·전매제한 동반 — 자금·거주계획 우선 점검",
        ),
    ),
)

_US_EVERGREEN = (
    RealEstateTopic(
        title="미국 부동산 투자 경로 · 세제",
        body="직접 매입(임대) vs 상장 REIT/ETF. 외국인·비거주자는 세제·신고를 사전 점검하세요.",
        bullets=(
            "보유: property tax(주·카운티별 상이)·보험(플로리다 등 급등)·관리·공실",
            "양도: FIRPTA(외국인 양도 원천징수), 1031 exchange(양도세 이연)",
            "한국 거주자: 해외부동산 취득·보유·처분 신고 + 임대소득 신고 + 환리스크",
        ),
    ),
    RealEstateTopic(
        title="모기지 금리 · 연준 경로",
        body="모기지 금리는 매수여력·리파이낸싱·REIT 밸류의 1차 변수 — Fed Watcher와 직접 연동됩니다.",
        bullets=(
            "금리↑: 매수여력↓·캡레이트↑로 가격 압박",
            "금리↓ 기대: REIT·홈빌더 리레이팅·거래 회복",
        ),
    ),
)

_US_POOL = (
    UsMarket(
        region="메릴랜드 (DC 근교)",
        state="MD",
        thesis="워싱턴 D.C. 인접 + 연방·군·바이오 클러스터로 경기 둔감한 임대 수요.",
        demand="연방 공무원·계약직·NIH/FDA·NSA(Fort Meade)·외국 주재원",
        risks="정부 셧다운·예산 변수, 지역별 가격 편차",
        profile="현금흐름+안정",
        best_for="공실 위험 낮은 안정적 장기 임대",
    ),
    UsMarket(
        region="댈러스–포트워스",
        state="TX",
        thesis="무주(無州)소득세 + 기업 본사 이전 + 인구·일자리 증가.",
        demand="기업 relocation, 제조·물류·금융 백오피스",
        risks="공급 과잉 국면·재산세 높음",
        profile="성장+현금흐름",
        best_for="인구 유입 기반 임대+시세",
    ),
    UsMarket(
        region="오스틴",
        state="TX",
        thesis="테크 허브·인구 유입. 팬데믹 급등 후 조정으로 진입 기회 가능.",
        demand="테슬라·반도체·스타트업 인력",
        risks="고점 대비 변동성·공급",
        profile="성장(변동성)",
        best_for="중장기 성장 베팅",
    ),
    UsMarket(
        region="탬파 / 잭슨빌",
        state="FL",
        thesis="무소득세 + 인구 유입(선벨트). 상대적 저평가.",
        demand="은퇴·이주 인구, 물류·헬스케어",
        risks="주택보험료 급등·허리케인",
        profile="현금흐름+이주수요",
        best_for="임대수익률+인구 성장",
    ),
    UsMarket(
        region="내슈빌",
        state="TN",
        thesis="무소득세 + 헬스케어·음악·관광 경제, 강한 인구 유입.",
        demand="헬스케어 본사, 관광·엔터",
        risks="단기임대 규제·공급",
        profile="성장+현금흐름",
        best_for="성장 도시 분산",
    ),
    UsMarket(
        region="롤리–더럼 (리서치 트라이앵글)",
        state="NC",
        thesis="대학·바이오·테크 클러스터, 고학력 인구 유입.",
        demand="제약·반도체·대학",
        risks="신규 공급",
        profile="안정+성장",
        best_for="고소득 임차 수요",
    ),
    UsMarket(
        region="샬럿",
        state="NC",
        thesis="동부 금융 허브(뱅크오브아메리카 등) + 선벨트 성장.",
        demand="금융·핀테크",
        risks="금융 경기 민감",
        profile="균형",
        best_for="안정적 도시 성장",
    ),
    UsMarket(
        region="피닉스",
        state="AZ",
        thesis="캘리포니아 대비 가성비 이주 + 반도체(TSMC) 투자.",
        demand="이주 인구·반도체",
        risks="금리 민감·물 부족 장기 리스크",
        profile="성장(금리민감)",
        best_for="이주·산업 유치 베팅",
    ),
    UsMarket(
        region="컬럼버스",
        state="OH",
        thesis="인텔 대형 팹 투자 + 중서부 저평가·높은 임대수익률.",
        demand="반도체·물류·대학(OSU)",
        risks="중서부 인구 성장 완만",
        profile="현금흐름(고수익률)",
        best_for="캡레이트 높은 현금흐름",
    ),
    UsMarket(
        region="헌츠빌",
        state="AL",
        thesis="항공우주·방산(Redstone Arsenal/NASA) 엔지니어 일자리, 저렴한 진입가.",
        demand="방산·항공우주·엔지니어",
        risks="단일 산업 의존",
        profile="현금흐름+안정",
        best_for="정부·방산 수요 기반 임대",
    ),
)

_INSTRUMENTS = (
    RealEstateInstrument(
        ticker="O",
        name="Realty Income",
        kind="REIT",
        note="월배당 net-lease REIT, 점유율 ~98.9%, 배당 5%대, 57년 연속 배당.",
    ),
    RealEstateInstrument(
        ticker="ADC",
        name="Agree Realty",
        kind="REIT",
        note="월배당 net-lease REIT — 우량 리테일 임차인 중심 성장형 배당.",
    ),
    RealEstateInstrument(
        ticker="XHB",
        name="SPDR S&P Homebuilders",
        kind="HOMEBUILDER",
        note="동일가중 — 빌더 + 홈임프루브먼트·건자재 공급사 포함.",
    ),
    RealEstateInstrument(
        ticker="ITB",
        name="iShares U.S. Home Construction",
        kind="HOMEBUILDER",
        note="순수 홈빌더 집중(D.R. Horton·Lennar) — 주택 사이클 직접 베팅.",
    ),
    RealEstateInstrument(
        ticker="PAVE",
        name="Global X U.S. Infrastructure",
        kind="MATERIALS_INFRA",
        note="인프라·건자재·중장비 — 재정·인프라 지출 수혜.",
    ),
    RealEstateInstrument(
        ticker="088980",
        name="맥쿼리인프라",
        kind="KR_REIT",
        note="국내 상장 인프라 펀드 — 배당형(참고용).",
    ),
)

_REGULATIONS = (
    RealEstateTopic(
        title="한국 제도",
        bullets=(
            "대출: LTV·DSR이 매수여력의 핵심(스트레스 DSR 단계 확대 점검)",
            "세금: 취득세·종합부동산세·양도소득세(다주택 중과 여부)",
            "정비/공급: 분양가상한제·재초환·전월세신고제·토지거래허가구역",
        ),
    ),
    RealEstateTopic(
        title="미국 제도",
        bullets=(
            "property tax(주·카운티)·mortgage interest deduction",
            "1031 like-kind exchange(양도세 이연), FIRPTA(외국인 양도 원천징수)",
            "REIT 배당 대부분 ordinary income — 절세계좌 배치 고려",
        ),
    ),
)

_NOTES = (
    "한국 금리 환경은 한국은행(BOK) 기준, 미국은 연준(Fed) 기준으로 분리 적용합니다.",
    "한국 단지·청약은 참고용 워치리스트 + 검색 딥링크이며 실거래·청약홈에서 반드시 확인하세요(라이브 매물 아님).",
    "미국 지역 추천은 매일 로테이션되며, 메릴랜드는 예시 중 하나입니다. 구체 수치는 실거래·세금·보험·환율로 검증하세요.",
    "정보·교육용이며 투자 권유가 아닙니다(면책). 그 전제 하에 권고는 과감히 제시합니다.",
)


def select_us_markets(ordinal: int, n: int = 4) -> tuple[UsMarket, ...]:
    """Deterministic daily rotation: shifts by one market per day, covering the pool."""
    size = len(_US_POOL)
    start = ordinal % size
    return tuple(_US_POOL[(start + i) % size] for i in range(min(n, size)))


def _kr_rate(stance: str, hikes: int) -> tuple[str, str]:
    s = stance.lower()
    if s == "hawkish":
        hk = f" (2026년 약 {hikes}회 인상 전망)" if hikes else ""
        return (
            f"긴축·금리 인상{hk}",
            "역풍 — 대출규제·DSR·금리 부담으로 매수여력 위축. 핵심지/현금흐름 위주, 레버리지 매수 신중. "
            "금리 인상기엔 갭·전세 레버리지 리스크 관리가 우선입니다.",
        )
    if s == "dovish":
        return (
            "완화·금리 인하 기대",
            "순풍 — 인하 기대 시 핵심지·재건축 선반영 가능. 단, 대출·세제 규제 병행 확인.",
        )
    return ("중립", "관망 — 입지·정책 이벤트(공급·청약·정비·교통) 중심 선별 접근.")


def _us_rate(fed_sign: int) -> tuple[str, str]:
    if fed_sign > 0:
        return (
            "긴축·고금리",
            "역풍 — 모기지 부담·캡레이트 상승. 배당 net-lease(O·ADC) 등 현금흐름 우선.",
        )
    if fed_sign < 0:
        return ("완화·인하 기대", "순풍 — REIT·홈빌더(XHB·ITB) 리레이팅·거래 회복 우호.")
    return ("중립", "선별 — 우량 임차인·점유율 높은 net-lease REIT 중심.")


def build_realestate_view(
    regime: RegimeAssessment,
    signals: list[NormalizedSignal],
    *,
    korea_stance: str,
    korea_hikes: int,
    us_markets: tuple[UsMarket, ...],
    us_archive: tuple[ArchiveEntry, ...],
    re_news: tuple[str, ...],
    kr_redev: tuple[KrListing, ...],
) -> RealEstateView:
    fed = extract_features(signals).fed_stance
    fed_sign = 1 if fed > 0.1 else -1 if fed < -0.1 else 0
    kr_env, kr_stance = _kr_rate(korea_stance, korea_hikes)
    us_env, us_stance = _us_rate(fed_sign)
    stance = RealEstateStance(
        kr_rate_env=kr_env,
        us_rate_env=us_env,
        kr_stance=kr_stance,
        us_stance=us_stance,
        rationale="한국 부동산은 한국은행(BOK) 금리, 미국 부동산은 연준(Fed) 금리에 연동해 평가합니다.",
    )
    return RealEstateView(
        as_of=regime.as_of,
        stance=stance,
        kr_topics=_KR_TOPICS,
        kr_rail=_KR_RAIL,
        kr_listings=_KR_LISTINGS,
        kr_redev=kr_redev,
        kr_redev_pinned=_KR_REDEV_PINNED,
        kr_strategy=_KR_STRATEGY,
        kr_subscriptions=_KR_SUBSCRIPTIONS,
        us_markets=us_markets,
        us_evergreen=_US_EVERGREEN,
        us_archive=us_archive,
        instruments=_INSTRUMENTS,
        regulations=_REGULATIONS,
        re_news=re_news,
        notes=_NOTES,
    )
