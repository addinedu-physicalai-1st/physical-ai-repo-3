/* floorplan-view.js — 매장 평면도 (tview.png + 동적 마커 overlay, 2026-05-17 복구)
 *
 * 구조: SVG viewBox "0 0 1251 788" 안에 tview.png 임베드 + 마커 4종.
 *   - HOME 마커 (정적 사각형 outline + yaw 화살표)
 *   - 테이블 T01~T05 (동적 occupancy 색상 사각형, yaw 회전, store.tables 바인딩)
 *   - gate1~3 (정적 사각형 outline, yaw 회전, 출입구 entry point)
 *   - robot 마커 (동적 transform 사각형 + 화살표, store.robot_pose 바인딩)
 *
 * 좌표 변환 (ROS map → tview.png 픽셀):
 *   T01~T05 라벨 박스 5개 검출 → 5점 affine least-squares (잔차 ≤ ±2px).
 *   px = 82.2331*x + 2.5426*y + 4010.7028
 *   py = -0.8722*x - 79.5863*y + 374.5820
 *   yaw (rad) → SVG rotate(deg) = -yaw * 180/π (ROS y+ = up, SVG y+ = down)
 *
 *   HOME 마커 위치는 affine 과 약간 어긋남 (ROS x scale 만 비일치) — tview.png 안
 *   소문자 "home" 라벨 박스 (px=965, py=174) 직접 사용. robot 마커는 affine 일관.
 *
 * 갱신 패턴: DOM 재생성 X. transform / class 만 부분 갱신 (mode-badge 패턴 정합).
 */

class FloorplanView extends HTMLElement {
  static toPx(x, y) { return 82.2331 * x +  2.5426 * y + 4010.7028; }
  static toPy(x, y) { return -0.8722 * x + -79.5863 * y +  374.5820; }
  static toDeg(yaw) { return -yaw * 180 / Math.PI; }

  // tables.yaml sync (2026-05-17 갱신 — place_furniture_picker 등록 robot 정차 좌표).
  // pose 자체가 robot 정차 위치 (테이블 옆 통로) + 정차 yaw.
  static TABLES = [
    { id: 'T01', x: -37.120, y:  0.543, yaw: -1.570 },
    { id: 'T02', x: -40.303, y: -0.591, yaw:  1.571 },
    { id: 'T03', x: -40.287, y:  0.276, yaw:  1.571 },
    { id: 'T04', x: -45.653, y:  0.276, yaw: -1.571 },
    { id: 'T05', x: -45.670, y: -0.557, yaw: -1.571 },
  ];
  // HOME 마커 — tview.png 소문자 "home" 라벨 박스 직접 (px=965, py=174). yaw=-π/2 남쪽.
  static HOME_PX = 965;
  static HOME_PY = 174;
  static HOME_DEG = FloorplanView.toDeg(-1.5708);   // = +90

  // gate1~3 — cafe_layout.yaml sync (2026-05-17 등록). yaw = 안→밖 방향.
  static GATES = [
    { id: 'gate1', x: -38.153, y: -1.757, yaw: -1.570 },
    { id: 'gate2', x: -39.353, y: -1.824, yaw:  1.571 },
    { id: 'gate3', x: -45.803, y: -2.024, yaw: -1.570 },
  ];

  // 마커 size (SVG units, viewBox 1251×788)
  static TABLE_W = 48; static TABLE_H = 36;       // 정차 박스 + 라벨 가운데
  static HOME_W  = 50; static HOME_H  = 38;
  // GATE: long edge 가 yaw 수직 (= 문 폭). GATE_W=yaw 방향 두께, GATE_H=문 폭.
  static GATE_W  = 18; static GATE_H  = 74;
  static ROBOT_W = 30; static ROBOT_H = 24;       // Vic Pinky footprint 약 비율

  connectedCallback() {
    this._build();
    if (window.store) {
      store.on('robot_pose', (p) => this._updateRobot(p));
      store.on('tables', (t) => this._updateTables(t));
    }
  }

  _build() {
    // 테이블 5종
    const tw = FloorplanView.TABLE_W, th = FloorplanView.TABLE_H;
    const tableGroups = FloorplanView.TABLES.map(t => {
      const px = FloorplanView.toPx(t.x, t.y);
      const py = FloorplanView.toPy(t.x, t.y);
      const deg = FloorplanView.toDeg(t.yaw);
      return `
        <g id="fp-table-${t.id}" class="fp-table fp-table-unknown"
           transform="translate(${px.toFixed(1)}, ${py.toFixed(1)}) rotate(${deg.toFixed(1)})">
          <rect x="${-tw/2}" y="${-th/2}" width="${tw}" height="${th}" rx="4" />
          <text y="6" text-anchor="middle">${t.id}</text>
        </g>
      `;
    }).join('');

    // gate 3종 (정적)
    const gw = FloorplanView.GATE_W, gh = FloorplanView.GATE_H;
    const gateGroups = FloorplanView.GATES.map(g => {
      const px = FloorplanView.toPx(g.x, g.y);
      const py = FloorplanView.toPy(g.x, g.y);
      const deg = FloorplanView.toDeg(g.yaw);
      return `
        <g class="fp-gate" transform="translate(${px.toFixed(1)}, ${py.toFixed(1)}) rotate(${deg.toFixed(1)})">
          <rect x="${-gw/2}" y="${-gh/2}" width="${gw}" height="${gh}" rx="3" />
          <text y="${-gh/2 - 6}" text-anchor="middle">${g.id}</text>
        </g>
      `;
    }).join('');

    // HOME 정적 사각형 + 라벨
    const hw = FloorplanView.HOME_W, hh = FloorplanView.HOME_H;
    const home_px = FloorplanView.HOME_PX, home_py = FloorplanView.HOME_PY;
    const home_deg = FloorplanView.HOME_DEG;

    // robot 초기 = HOME 위치 + HOME yaw 동일 방향
    const rw = FloorplanView.ROBOT_W, rh = FloorplanView.ROBOT_H;

    this.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg"
           viewBox="0 0 1251 788"
           preserveAspectRatio="xMidYMid meet"
           aria-label="MOCA 매장 평면도 — robot pose + 테이블 점유 실시간">
        <image href="/static/assets/tview.png?v=20260517l"
               x="0" y="0" width="1251" height="788"
               preserveAspectRatio="none" />

        <!-- HOME pose 정적 사각형 outline + 라벨 -->
        <g class="fp-home" transform="translate(${home_px}, ${home_py}) rotate(${home_deg})">
          <rect x="${-hw/2}" y="${-hh/2}" width="${hw}" height="${hh}" rx="4" />
          <text y="${-hh/2 - 6}" text-anchor="middle">HOME</text>
        </g>

        <!-- 테이블 5종 -->
        ${tableGroups}

        <!-- gate 3종 -->
        ${gateGroups}

        <!-- 로봇 마커 (사각형 + 화살표).
             ROS yaw=-π/2 (home) → SVG rotate(+90) = 화살표 아래쪽 (남쪽). -->
        <g id="fp-robot" class="fp-robot"
           transform="translate(${home_px}, ${home_py}) rotate(${home_deg})">
          <rect class="fp-robot-body" x="${-rw/2}" y="${-rh/2}" width="${rw}" height="${rh}" rx="3" />
          <path class="fp-robot-arrow" d="M ${rw/2 - 8},${-rh/2 + 4} L ${rw/2 + 6},0 L ${rw/2 - 8},${rh/2 - 4} Z" />
        </g>
      </svg>
    `;

    this._robot = this.querySelector('#fp-robot');
    this._tableEls = {};
    FloorplanView.TABLES.forEach(t => {
      this._tableEls[t.id] = this.querySelector(`#fp-table-${t.id}`);
    });
    this._lastTableCls = {};
  }

  _updateRobot(pose) {
    if (!pose || !this._robot) return;
    const x = (typeof pose.x === 'number') ? pose.x : 0;
    const y = (typeof pose.y === 'number') ? pose.y : 0;
    const yaw = (typeof pose.yaw === 'number') ? pose.yaw : 0;
    const px = FloorplanView.toPx(x, y);
    const py = FloorplanView.toPy(x, y);
    const deg = FloorplanView.toDeg(yaw);
    this._robot.setAttribute('transform', `translate(${px.toFixed(1)}, ${py.toFixed(1)}) rotate(${deg.toFixed(1)})`);
  }

  _updateTables(tables) {
    if (!tables || !this._tableEls) return;
    for (const tid of Object.keys(this._tableEls)) {
      const row = tables[tid];
      const occ = (row && row.occupancy) || 'unknown';
      const cls = `fp-table fp-table-${occ}`;
      if (this._lastTableCls[tid] !== cls) {
        this._tableEls[tid].setAttribute('class', cls);
        this._lastTableCls[tid] = cls;
      }
    }
  }
}

customElements.define('floorplan-view', FloorplanView);
