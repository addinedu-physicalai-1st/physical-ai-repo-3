import random
import hashlib
from datetime import datetime, timedelta
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from style import (
    BG, SIDEBAR, SB_HV, SB_ACT, PRIMARY, SUCCESS, WARNING, ERROR, PURPLE,
    CYAN, ORANGE, CARD, BORDER, TEXT, TEXT2, TEXT3,
)


# ═══════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def mkbtn(text, color=None, small=False):
    b = QPushButton(text)
    c = color or PRIMARY
    pad = '6px 14px' if small else '9px 22px'
    fs  = '12px'     if small else '13px'
    b.setStyleSheet(f"""
        QPushButton {{
            background:{c}; color:#fff; border:none; border-radius:7px;
            font-size:{fs}; font-weight:700; padding:{pad};
        }}
        QPushButton:hover   {{ background:{c}dd; }}
        QPushButton:pressed  {{ background:{c}99; }}
        QPushButton:disabled {{ background:#E2E8F0; color:{TEXT3}; }}
    """)
    return b


def mkobtn(text, color=None):
    b = QPushButton(text)
    c = color or PRIMARY
    b.setStyleSheet(f"""
        QPushButton {{
            background:transparent; color:{c}; border:2px solid {c};
            border-radius:7px; font-size:13px; font-weight:700; padding:7px 18px;
        }}
        QPushButton:hover   {{ background:{c}18; }}
        QPushButton:pressed  {{ background:{c}33; }}
    """)
    return b


def mklbl(text, size=13, bold=False, color=None):
    l = QLabel(text)
    c = color or TEXT
    w = 700 if bold else 400
    l.setStyleSheet(f"font-size:{size}px; font-weight:{w}; color:{c}; background:transparent;")
    return l


def mkbadge(text, color):
    l = QLabel(f" {text} ")
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setFixedHeight(22)
    l.setStyleSheet(f"""
        background:{color}22; color:{color}; border-radius:11px;
        font-size:11px; font-weight:700; padding:0px 8px; border:1px solid {color}44;
    """)
    return l


def hdivider():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER}; max-height:1px; background:{BORDER};")
    return f


def wrap_scroll(widget):
    s = QScrollArea()
    s.setWidget(widget)
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setStyleSheet("background:transparent;")
    return s


def card_frame(title=''):
    f = QFrame()
    f.setObjectName('cardFrame')
    f.setStyleSheet(f"""
        QFrame#cardFrame {{
            background:{CARD}; border-radius:12px; border:1px solid {BORDER};
        }}
    """)
    vl = QVBoxLayout(f)
    vl.setContentsMargins(20, 18, 20, 18)
    vl.setSpacing(12)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size:15px; font-weight:700; color:{TEXT}; background:transparent;")
        vl.addWidget(lbl)
    return f, vl


def make_table(headers, stretch_last=True):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    if not stretch_last:
        t.horizontalHeader().setSectionResizeMode(
            len(headers)-1, QHeaderView.ResizeMode.ResizeToContents)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setShowGrid(True)
    t.setStyleSheet(f"alternate-background-color:#F8FAFC;")
    return t


def page_header(title, subtitle=''):
    w = QWidget()
    w.setObjectName('pageHeader')
    w.setStyleSheet(f"QWidget#pageHeader{{background:{CARD}; border-bottom:1px solid {BORDER};}}")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(28, 18, 28, 18)
    vl = QVBoxLayout()
    vl.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"font-size:22px; font-weight:800; color:{TEXT}; background:transparent;")
    vl.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size:13px; color:{TEXT2}; background:transparent;")
        vl.addWidget(s)
    hl.addLayout(vl)
    hl.addStretch()
    return w


# ═══════════════════════════════════════════════════════════════════
#  PAGE 1 — MAP MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

class MapCanvas(QWidget):
    FACILITIES = {
        'coffee': ('☕', '#92400E', '커피트럭'),
        'table':  ('🪑', '#1D4ED8', '테이블'),
        'robot':  ('🤖', '#059669', '로봇 대기'),
    }
    LIMITS = {'coffee': 1, 'table': 4, 'robot': 99}

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 360)
        self.facilities = []
        self.selected_id = None
        self.placing = None
        self._nid = 1
        self.grid = 30
        self.setMouseTracking(True)
        self._drag_offset = QPoint()

    def set_placing(self, ftype):
        self.placing = ftype
        self.setCursor(Qt.CursorShape.CrossCursor if ftype else Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor('#FAFBFE'))

        # Grid
        p.setPen(QPen(QColor('#E2E8F0'), 1))
        for x in range(0, self.width(), self.grid):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), self.grid):
            p.drawLine(0, y, self.width(), y)

        # Border
        p.setPen(QPen(QColor(PRIMARY), 2))
        p.drawRect(1, 1, self.width()-2, self.height()-2)

        # Facilities
        for fac in self.facilities:
            icon, color, name = self.FACILITIES[fac['type']]
            x, y = fac['x'], fac['y']
            is_sel = self.selected_id == fac['id']

            if is_sel:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(color), 2, Qt.PenStyle.DashLine))
                p.drawEllipse(x-26, y-26, 52, 52)

            bg = QColor(color)
            bg.setAlpha(30)
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor(color), 1.5))
            p.drawEllipse(x-20, y-20, 40, 40)

            font = QFont()
            font.setPointSize(16)
            p.setFont(font)
            p.setPen(Qt.GlobalColor.black)
            p.drawText(QRect(x-18, y-18, 36, 36), Qt.AlignmentFlag.AlignCenter, icon)

            sf = QFont()
            sf.setPointSize(8)
            sf.setBold(True)
            p.setFont(sf)
            p.setPen(QColor(color))
            p.drawText(QRect(x-32, y+22, 64, 14), Qt.AlignmentFlag.AlignCenter,
                       fac.get('label', name))

    def _fac_at(self, x, y):
        for fac in reversed(self.facilities):
            if (x-fac['x'])**2 + (y-fac['y'])**2 <= 400:
                return fac
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.placing:
                count = sum(1 for f in self.facilities if f['type'] == self.placing)
                limit = self.LIMITS[self.placing]
                if count >= limit:
                    QMessageBox.warning(self, '배치 제한',
                        f"{'커피트럭은 1개' if self.placing=='coffee' else f'{self.FACILITIES[self.placing][2]}는 최대 {limit}개'}만 배치 가능합니다.")
                    return
                fac = {
                    'type': self.placing, 'x': e.position().x(), 'y': e.position().y(),
                    'id': self._nid,
                    'label': f"{self.FACILITIES[self.placing][2]} {self._nid}"
                }
                self._nid += 1
                self.facilities.append(fac)
                self.selected_id = fac['id']
                self.update()
            else:
                px, py = int(e.position().x()), int(e.position().y())
                fac = self._fac_at(px, py)
                self.selected_id = fac['id'] if fac else None
                if fac:
                    self._drag_offset = QPoint(
                        px - fac['x'], py - fac['y'])
                self.update()

        elif e.button() == Qt.MouseButton.RightButton:
            px, py = int(e.position().x()), int(e.position().y())
            fac = self._fac_at(px, py)
            if fac:
                self.facilities.remove(fac)
                if self.selected_id == fac['id']:
                    self.selected_id = None
                self.update()

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.MouseButton.LeftButton
                and self.selected_id and not self.placing):
            px, py = int(e.position().x()), int(e.position().y())
            for fac in self.facilities:
                if fac['id'] == self.selected_id:
                    fac['x'] = px - self._drag_offset.x()
                    fac['y'] = py - self._drag_offset.y()
                    break
            self.update()

    def delete_selected(self):
        self.facilities = [f for f in self.facilities if f['id'] != self.selected_id]
        self.selected_id = None
        self.update()

    def clear_all(self):
        self.facilities.clear()
        self.selected_id = None
        self._nid = 1
        self.update()


class MapManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        self.maps = [
            {'id': 1, 'name': '1층 로비', 'location': '서울 강남구 테헤란로 123', 'w': 20.0, 'h': 15.0},
            {'id': 2, 'name': '2층 테라스', 'location': '서울 강남구 테헤란로 123', 'w': 30.0, 'h': 10.0},
        ]
        self._nid = 3
        self._cur = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('서비스 지역 지도 관리', '지도 생성·수정·삭제 및 시설 배치'))

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(20)
        root.addWidget(body, 1)

        # ── Left list ──
        left = QWidget()
        left.setMaximumWidth(260)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addWidget(mklbl('지도 목록', 14, True))

        row = QHBoxLayout()
        b_add = mkbtn('+ 추가', small=True)
        b_add.clicked.connect(self._add_map)
        b_del = mkbtn('삭제', ERROR, small=True)
        b_del.clicked.connect(self._del_map)
        row.addWidget(b_add); row.addWidget(b_del); row.addStretch()
        ll.addLayout(row)

        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self._select)
        ll.addWidget(self.lst, 1)
        self._refresh_list()
        bl.addWidget(left)

        # ── Right editor ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(16)

        # Props card
        pcard, pl = card_frame('지도 속성')
        pcard.setMaximumHeight(175)
        g = QGridLayout()
        g.setSpacing(10)
        self.e_name = QLineEdit(); self.e_name.setPlaceholderText('지도 이름')
        self.e_loc  = QLineEdit(); self.e_loc.setPlaceholderText('위치/주소')
        self.e_w = QDoubleSpinBox(); self.e_w.setRange(1, 9999); self.e_w.setSuffix(' m'); self.e_w.setValue(20)
        self.e_h = QDoubleSpinBox(); self.e_h.setRange(1, 9999); self.e_h.setSuffix(' m'); self.e_h.setValue(15)
        g.addWidget(mklbl('이름', bold=True),  0, 0); g.addWidget(self.e_name, 0, 1)
        g.addWidget(mklbl('위치', bold=True),  0, 2); g.addWidget(self.e_loc,  0, 3)
        g.addWidget(mklbl('너비', bold=True),  1, 0); g.addWidget(self.e_w,    1, 1)
        g.addWidget(mklbl('높이', bold=True),  1, 2); g.addWidget(self.e_h,    1, 3)
        pl.addLayout(g)
        sr = QHBoxLayout(); sr.addStretch()
        b_save = mkbtn('저장')
        b_save.clicked.connect(self._save_props)
        sr.addWidget(b_save)
        pl.addLayout(sr)
        rl.addWidget(pcard)

        # Canvas card
        ccard, cl = card_frame('시설 배치')
        self.canvas = MapCanvas()

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(mklbl('배치:', bold=True))
        colors = {'coffee': '#92400E', 'table': '#1D4ED8', 'robot': '#059669'}
        for ftype, (icon, color, name) in MapCanvas.FACILITIES.items():
            b = mkbtn(f'{icon} {name}', colors[ftype], small=True)
            b.clicked.connect(lambda checked, t=ftype: self.canvas.set_placing(t))
            toolbar.addWidget(b)

        b_sel = mkobtn('↖ 이동/선택')
        b_sel.clicked.connect(lambda: self.canvas.set_placing(None))
        b_del2 = mkbtn('🗑 선택삭제', ERROR, small=True)
        b_del2.clicked.connect(self.canvas.delete_selected)
        b_clr = mkbtn('전체삭제', WARNING, small=True)
        b_clr.clicked.connect(self._clear_canvas)
        toolbar.addWidget(b_sel); toolbar.addWidget(b_del2); toolbar.addWidget(b_clr)
        toolbar.addStretch()
        toolbar.addWidget(mklbl('우클릭: 삭제 | 드래그: 이동', 11, color=TEXT3))

        cl.addLayout(toolbar)
        cl.addWidget(self.canvas, 1)
        rl.addWidget(ccard, 1)
        bl.addWidget(right, 1)

    def _refresh_list(self):
        self.lst.clear()
        for m in self.maps:
            self.lst.addItem(f"📍 {m['name']}\n   {m['location']}")

    def _select(self, row):
        if 0 <= row < len(self.maps):
            m = self.maps[row]; self._cur = m
            self.e_name.setText(m['name']); self.e_loc.setText(m['location'])
            self.e_w.setValue(m['w']); self.e_h.setValue(m['h'])

    def _add_map(self):
        name, ok = QInputDialog.getText(self, '새 지도', '지도 이름:')
        if ok and name.strip():
            m = {'id': self._nid, 'name': name.strip(), 'location': '', 'w': 20.0, 'h': 15.0}
            self._nid += 1; self.maps.append(m)
            self._refresh_list(); self.lst.setCurrentRow(len(self.maps)-1)

    def _del_map(self):
        r = self.lst.currentRow()
        if r < 0: return
        if QMessageBox.question(self, '삭제 확인',
            f"'{self.maps[r]['name']}' 지도를 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.maps.pop(r); self._cur = None; self._refresh_list()

    def _save_props(self):
        if not self._cur:
            QMessageBox.information(self, '안내', '저장할 지도를 먼저 선택하세요.')
            return
        self._cur.update({'name': self.e_name.text(), 'location': self.e_loc.text(),
                          'w': self.e_w.value(), 'h': self.e_h.value()})
        self._refresh_list()
        QMessageBox.information(self, '저장 완료', '지도 정보가 저장되었습니다.')

    def _clear_canvas(self):
        if QMessageBox.question(self, '확인', '모든 시설을 삭제할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.canvas.clear_all()


# ═══════════════════════════════════════════════════════════════════
#  PAGE 2 — ADMIN INFO MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

class AdminDialog(QDialog):
    RANKS = ['최고관리자', '관리자', '운영자', '모니터요원']

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle('관리자 정보' + (' 수정' if data else ' 추가'))
        self.setMinimumWidth(380)
        self.data = data or {}
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(14)
        vl.addWidget(mklbl('관리자 정보 입력', 16, True))

        g = QFormLayout()
        g.setSpacing(10)
        self.c_rank = QComboBox(); self.c_rank.addItems(self.RANKS)
        if self.data.get('rank'): self.c_rank.setCurrentText(self.data['rank'])
        self.e_id   = QLineEdit(self.data.get('uid', ''))
        self.e_id.setPlaceholderText('영문+숫자 조합')
        self.e_name = QLineEdit(self.data.get('name', ''))
        self.e_pw   = QLineEdit(); self.e_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_pw.setPlaceholderText('변경 시에만 입력')
        self.e_pw2  = QLineEdit(); self.e_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_pw2.setPlaceholderText('비밀번호 확인')
        g.addRow(mklbl('직급', bold=True),          self.c_rank)
        g.addRow(mklbl('아이디', bold=True),         self.e_id)
        g.addRow(mklbl('이름', bold=True),           self.e_name)
        g.addRow(mklbl('비밀번호', bold=True),       self.e_pw)
        g.addRow(mklbl('비밀번호 확인', bold=True),  self.e_pw2)
        vl.addLayout(g)

        vl.addWidget(hdivider())
        row = QHBoxLayout(); row.addStretch()
        b_cancel = mkobtn('취소'); b_cancel.clicked.connect(self.reject)
        b_ok = mkbtn('저장');     b_ok.clicked.connect(self._submit)
        row.addWidget(b_cancel); row.addWidget(b_ok)
        vl.addLayout(row)

    def _submit(self):
        uid  = self.e_id.text().strip()
        name = self.e_name.text().strip()
        pw   = self.e_pw.text()
        pw2  = self.e_pw2.text()
        if not uid or not name:
            QMessageBox.warning(self, '입력 오류', '아이디와 이름을 입력하세요.')
            return
        if pw and pw != pw2:
            QMessageBox.warning(self, '입력 오류', '비밀번호가 일치하지 않습니다.')
            return
        self.result_data = {
            'rank': self.c_rank.currentText(), 'uid': uid, 'name': name,
            'pw_hash': hashlib.sha256(pw.encode()).hexdigest() if pw
                       else self.data.get('pw_hash', ''),
        }
        self.accept()


class AdminInfoPage(QWidget):
    def __init__(self):
        super().__init__()
        self.admins = [
            {'id': 1, 'rank': '최고관리자', 'uid': 'admin', 'name': '홍길동',
             'pw_hash': hashlib.sha256(b'admin1234').hexdigest()},
            {'id': 2, 'rank': '관리자',    'uid': 'manager1', 'name': '김영희',
             'pw_hash': hashlib.sha256(b'pass0000').hexdigest()},
            {'id': 3, 'rank': '운영자',    'uid': 'op01', 'name': '이철수',
             'pw_hash': hashlib.sha256(b'op1234').hexdigest()},
        ]
        self._nid = 4
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(page_header('관리자 정보 관리', '관리자 계정 생성·수정·삭제'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24, 24, 24, 24); bl.setSpacing(16)
        root.addWidget(body, 1)

        tr = QHBoxLayout()
        b_add  = mkbtn('+ 관리자 추가'); b_add.clicked.connect(self._add)
        b_edit = mkbtn('수정', WARNING);  b_edit.clicked.connect(self._edit)
        b_del  = mkbtn('삭제', ERROR);    b_del.clicked.connect(self._delete)
        tr.addWidget(b_add); tr.addWidget(b_edit); tr.addWidget(b_del); tr.addStretch()
        bl.addLayout(tr)

        self.table = make_table(['#', '직급', '아이디', '이름', '등록일'])
        bl.addWidget(self.table, 1)
        self._refresh()

    def _refresh(self):
        self.table.setRowCount(0)
        for a in self.admins:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(a['id'])))
            self.table.setItem(r, 1, QTableWidgetItem(a['rank']))
            self.table.setItem(r, 2, QTableWidgetItem(a['uid']))
            self.table.setItem(r, 3, QTableWidgetItem(a['name']))
            self.table.setItem(r, 4, QTableWidgetItem('2025-01-01'))

    def _selected(self):
        r = self.table.currentRow()
        return self.admins[r] if r >= 0 else None

    def _add(self):
        dlg = AdminDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_data; d['id'] = self._nid
            self._nid += 1; self.admins.append(d); self._refresh()

    def _edit(self):
        a = self._selected()
        if not a:
            QMessageBox.information(self, '안내', '수정할 관리자를 선택하세요.')
            return
        dlg = AdminDialog(self, a)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            a.update(dlg.result_data); self._refresh()

    def _delete(self):
        a = self._selected()
        if not a:
            QMessageBox.information(self, '안내', '삭제할 관리자를 선택하세요.')
            return
        if (a['rank'] == '최고관리자'
                and sum(1 for x in self.admins if x['rank'] == '최고관리자') <= 1):
            QMessageBox.warning(self, '삭제 불가', '최고관리자는 최소 1명이어야 합니다.')
            return
        if QMessageBox.question(self, '삭제 확인',
            f"'{a['name']}({a['uid']})' 계정을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.admins.remove(a); self._refresh()


# ═══════════════════════════════════════════════════════════════════
#  PAGE 3 — PERMISSION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

class PermissionPage(QWidget):
    RANKS = ['최고관리자', '관리자', '운영자', '모니터요원']
    PERMS = [
        ('지도 관리',  '지도 생성/수정/삭제'),
        ('관리자 생성', '관리자 계정 추가'),
        ('관리자 수정', '관리자 계정 수정'),
        ('관리자 삭제', '관리자 계정 삭제'),
        ('권한 관리',  '권한 설정 변경'),
        ('메뉴 관리',  '상품 메뉴 CRUD'),
        ('모니터링',   '실시간 모니터링 조회'),
        ('로봇 제어',  '모드 전환/강제 발화'),
        ('로그 조회',  '시스템 로그 열람'),
        ('이상 감지',  '알림 수신 및 확인'),
        ('재고 관리',  '재고 수량 수정'),
        ('로봇 추가',  '로봇 장치 등록/삭제'),
    ]
    DEFAULT_PERMS = {
        '최고관리자': [True]*12,
        '관리자':    [True, True, True, True, False, True, True, True, True, True, True, True],
        '운영자':    [False,False,False,False,False,True,True,True,True,True,True,False],
        '모니터요원':[False,False,False,False,False,False,True,False,True,True,False,False],
    }

    def __init__(self):
        super().__init__()
        self.perms = {r: list(v) for r, v in self.DEFAULT_PERMS.items()}
        self._cur_rank = self.RANKS[0]
        self._checks = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(page_header('관리자 권한 관리', '직급별 기능 접근 권한 설정'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(body); bl.setContentsMargins(24, 24, 24, 24); bl.setSpacing(20)
        root.addWidget(body, 1)

        # Left: rank list
        left = QWidget(); left.setMaximumWidth(200)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        ll.addWidget(mklbl('직급 선택', 14, True))
        self.rank_list = QListWidget()
        for r in self.RANKS:
            self.rank_list.addItem(r)
        self.rank_list.setCurrentRow(0)
        self.rank_list.currentRowChanged.connect(self._rank_changed)
        ll.addWidget(self.rank_list, 1)
        bl.addWidget(left)

        # Right: permission matrix
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(12)

        self.rank_lbl = mklbl(self._cur_rank, 18, True, PRIMARY)
        rl.addWidget(self.rank_lbl)

        pcard, pl = card_frame('권한 설정')
        pg = QGridLayout(); pg.setSpacing(12)

        for i, (pname, pdesc) in enumerate(self.PERMS):
            row, col = divmod(i, 2)
            cb = QCheckBox(pname)
            cb.setToolTip(pdesc)
            cb.setChecked(self.perms[self._cur_rank][i])
            if self._cur_rank == '최고관리자':
                cb.setEnabled(False)
            self._checks.append(cb)
            pg.addWidget(cb, row, col)

        pl.addLayout(pg)
        rl.addWidget(pcard)

        btn_row = QHBoxLayout()
        b_all  = mkobtn('전체 선택');   b_all.clicked.connect(self._select_all)
        b_none = mkobtn('전체 해제', ERROR); b_none.clicked.connect(self._deselect_all)
        b_save = mkbtn('권한 저장');    b_save.clicked.connect(self._save)
        btn_row.addWidget(b_all); btn_row.addWidget(b_none)
        btn_row.addStretch(); btn_row.addWidget(b_save)
        rl.addLayout(btn_row)
        rl.addStretch()
        bl.addWidget(right, 1)

    def _rank_changed(self, row):
        if 0 <= row < len(self.RANKS):
            self._cur_rank = self.RANKS[row]
            self.rank_lbl.setText(self._cur_rank)
            for i, cb in enumerate(self._checks):
                cb.setChecked(self.perms[self._cur_rank][i])
                cb.setEnabled(self._cur_rank != '최고관리자')

    def _select_all(self):
        for cb in self._checks:
            if cb.isEnabled(): cb.setChecked(True)

    def _deselect_all(self):
        for cb in self._checks:
            if cb.isEnabled(): cb.setChecked(False)

    def _save(self):
        self.perms[self._cur_rank] = [cb.isChecked() for cb in self._checks]
        QMessageBox.information(self, '저장 완료',
            f"'{self._cur_rank}' 권한이 저장되었습니다.")


# ═══════════════════════════════════════════════════════════════════
#  PAGE 4 — PRODUCT MENU MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

class MenuDialog(QDialog):
    ALLERGENS = ['글루텐', '우유', '대두', '견과류', '계란', '복숭아', '새우', '게']
    ICE_TYPES  = ['기본 얼음', '크러쉬드 아이스', '얼음 없음']

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle('메뉴 ' + ('수정' if data else '추가'))
        self.setMinimumWidth(480)
        self.data = data or {}
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20); vl.setSpacing(14)
        vl.addWidget(mklbl('메뉴 정보', 16, True))

        g = QFormLayout(); g.setSpacing(10)
        self.e_no   = QLineEdit(self.data.get('no', ''))
        self.e_no.setPlaceholderText('예: M001')
        self.e_name = QLineEdit(self.data.get('name', ''))
        self.e_price = QSpinBox()
        self.e_price.setRange(0, 99999); self.e_price.setSuffix(' 원')
        self.e_price.setValue(self.data.get('price', 0)); self.e_price.setSingleStep(100)
        self.e_price.setMaximumWidth(160)
        self.cb_rep = QCheckBox('대표 메뉴로 지정')
        self.cb_rep.setChecked(self.data.get('is_rep', False))

        g.addRow(mklbl('상품번호', bold=True), self.e_no)
        g.addRow(mklbl('상품명', bold=True),   self.e_name)
        g.addRow(mklbl('가격', bold=True),     self.e_price)
        g.addRow(mklbl('대표 메뉴', bold=True), self.cb_rep)
        vl.addLayout(g)

        # Allergens
        ag = QGroupBox('알러지 정보')
        al = QGridLayout(ag); al.setSpacing(8)
        self._alg = {}
        for i, a in enumerate(self.ALLERGENS):
            cb = QCheckBox(a)
            cb.setChecked(a in self.data.get('allergens', []))
            self._alg[a] = cb
            al.addWidget(cb, i//4, i%4)
        vl.addWidget(ag)

        # Options
        og = QGroupBox('옵션')
        ol = QVBoxLayout(og); ol.setSpacing(8)
        self.cb_shot = QCheckBox('샷 추가 가능')
        self.cb_shot.setChecked(self.data.get('opt_shot', False))
        self.c_ice = QComboBox(); self.c_ice.addItems(self.ICE_TYPES)
        idx = self.ICE_TYPES.index(self.data.get('opt_ice', self.ICE_TYPES[0]))
        self.c_ice.setCurrentIndex(idx)
        self.cb_milk = QCheckBox('저지방 우유 선택 가능')
        self.cb_milk.setChecked(self.data.get('opt_milk', False))
        ice_row = QHBoxLayout()
        ice_row.addWidget(mklbl('얼음 종류:', bold=True))
        ice_row.addWidget(self.c_ice); ice_row.addStretch()
        ol.addWidget(self.cb_shot); ol.addLayout(ice_row); ol.addWidget(self.cb_milk)
        vl.addWidget(og)

        vl.addWidget(hdivider())
        row = QHBoxLayout(); row.addStretch()
        b_cancel = mkobtn('취소'); b_cancel.clicked.connect(self.reject)
        b_ok = mkbtn('저장');     b_ok.clicked.connect(self._submit)
        row.addWidget(b_cancel); row.addWidget(b_ok)
        vl.addLayout(row)

    def _submit(self):
        no   = self.e_no.text().strip()
        name = self.e_name.text().strip()
        if not no or not name:
            QMessageBox.warning(self, '입력 오류', '상품번호와 상품명을 입력하세요.')
            return
        self.result_data = {
            'no': no, 'name': name, 'price': self.e_price.value(),
            'is_rep': self.cb_rep.isChecked(),
            'allergens': [a for a, cb in self._alg.items() if cb.isChecked()],
            'opt_shot': self.cb_shot.isChecked(),
            'opt_ice':  self.c_ice.currentText(),
            'opt_milk': self.cb_milk.isChecked(),
        }
        self.accept()


class MenuPage(QWidget):
    def __init__(self):
        super().__init__()
        self.menus = [
            {'id':1,'no':'M001','name':'아메리카노','price':3500,'is_rep':True,
             'allergens':[],'opt_shot':True,'opt_ice':'기본 얼음','opt_milk':False},
            {'id':2,'no':'M002','name':'카페라떼','price':4000,'is_rep':False,
             'allergens':['우유'],'opt_shot':True,'opt_ice':'기본 얼음','opt_milk':True},
            {'id':3,'no':'M003','name':'카라멜 마끼아또','price':4500,'is_rep':True,
             'allergens':['우유','대두'],'opt_shot':True,'opt_ice':'크러쉬드 아이스','opt_milk':False},
            {'id':4,'no':'M004','name':'녹차 라떼','price':4200,'is_rep':False,
             'allergens':['우유'],'opt_shot':False,'opt_ice':'얼음 없음','opt_milk':True},
        ]
        self._nid = 5
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('상품 메뉴 관리', '음료 메뉴 등록·수정·삭제 및 대표 메뉴 지정'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(16)
        root.addWidget(body, 1)

        tr = QHBoxLayout()
        b_add  = mkbtn('+ 메뉴 추가'); b_add.clicked.connect(self._add)
        b_edit = mkbtn('수정', WARNING); b_edit.clicked.connect(self._edit)
        b_del  = mkbtn('삭제', ERROR);  b_del.clicked.connect(self._delete)
        tr.addWidget(b_add); tr.addWidget(b_edit); tr.addWidget(b_del); tr.addStretch()

        self.rep_lbl = mkbadge('대표 메뉴: —', PRIMARY)
        tr.addWidget(self.rep_lbl)
        bl.addLayout(tr)

        self.table = make_table(['상품번호','상품명','가격','알러지','옵션','대표'])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents)
        bl.addWidget(self.table, 1)
        self._refresh()

    def _refresh(self):
        self.table.setRowCount(0)
        reps = [m['name'] for m in self.menus if m['is_rep']]
        self.rep_lbl.setText(f" 대표 메뉴: {', '.join(reps) if reps else '없음'} ")
        for m in self.menus:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(m['no']))
            self.table.setItem(r, 1, QTableWidgetItem(m['name']))
            self.table.setItem(r, 2, QTableWidgetItem(f"{m['price']:,}원"))
            alg = ', '.join(m['allergens']) if m['allergens'] else '없음'
            self.table.setItem(r, 3, QTableWidgetItem(alg))
            opts = []
            if m['opt_shot']: opts.append('샷추가')
            if m['opt_milk']: opts.append('저지방')
            opts.append(m['opt_ice'])
            self.table.setItem(r, 4, QTableWidgetItem(' / '.join(opts)))
            self.table.setItem(r, 5, QTableWidgetItem('⭐ 대표' if m['is_rep'] else '—'))

    def _selected(self):
        r = self.table.currentRow()
        return self.menus[r] if r >= 0 else None

    def _add(self):
        dlg = MenuDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_data; d['id'] = self._nid
            self._nid += 1; self.menus.append(d); self._refresh()

    def _edit(self):
        m = self._selected()
        if not m:
            QMessageBox.information(self, '안내', '수정할 메뉴를 선택하세요.')
            return
        dlg = MenuDialog(self, m)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            m.update(dlg.result_data); self._refresh()

    def _delete(self):
        m = self._selected()
        if not m:
            QMessageBox.information(self, '안내', '삭제할 메뉴를 선택하세요.')
            return
        if QMessageBox.question(self, '삭제 확인',
            f"'{m['name']}' 메뉴를 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.menus.remove(m); self._refresh()


# ═══════════════════════════════════════════════════════════════════
#  PAGE 5 — REAL-TIME MONITORING
# ═══════════════════════════════════════════════════════════════════

class RobotCard(QFrame):
    STATUS_COLORS = {
        '정상대기': SUCCESS, '충전중': CYAN,
        '에러':     ERROR,   '오프라인': TEXT3,
    }

    def __init__(self, robot):
        super().__init__()
        self.robot = robot
        self.setObjectName('rcard')
        self.setStyleSheet(f"""
            QFrame#rcard {{
                background:{CARD}; border-radius:12px; border:1px solid {BORDER};
            }}
        """)
        self.setMinimumSize(240, 200)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        hr = QHBoxLayout()
        self._id_lbl = mklbl(self.robot['id'], 15, True)
        self._status_badge = mkbadge(self.robot['status'],
                                     self.STATUS_COLORS.get(self.robot['status'], TEXT3))
        hr.addWidget(self._id_lbl); hr.addStretch(); hr.addWidget(self._status_badge)
        lay.addLayout(hr)
        lay.addWidget(hdivider())

        brow = QHBoxLayout()
        brow.addWidget(mklbl('🔋 배터리', bold=True))
        self._bat_lbl = mklbl(f"{self.robot['battery']}%", color=TEXT2)
        brow.addStretch(); brow.addWidget(self._bat_lbl)
        lay.addLayout(brow)

        self._bat_bar = QProgressBar()
        self._bat_bar.setRange(0, 100)
        self._bat_bar.setValue(self.robot['battery'])
        self._bat_bar.setFixedHeight(8)
        self._bat_bar.setTextVisible(False)
        self._bat_bar.setStyleSheet(f"""
            QProgressBar {{ background:#F1F5F9; border-radius:4px; border:none; }}
            QProgressBar::chunk {{ background:{SUCCESS}; border-radius:4px; }}
        """)
        lay.addWidget(self._bat_bar)

        for key, icon in [('signal','📡 통신'), ('task','📋 작업'), ('damage','🛡 기물')]:
            row = QHBoxLayout()
            row.addWidget(mklbl(icon, bold=True))
            lbl = mklbl(self.robot[key], color=TEXT2)
            setattr(self, f'_{key}_lbl', lbl)
            row.addStretch(); row.addWidget(lbl)
            lay.addLayout(row)

    def update_data(self, robot):
        self.robot = robot
        self._id_lbl.setText(robot['id'])
        sc = self.STATUS_COLORS.get(robot['status'], TEXT3)
        self._status_badge.setText(f" {robot['status']} ")
        self._status_badge.setStyleSheet(f"""
            background:{sc}22; color:{sc}; border-radius:11px;
            font-size:11px; font-weight:700; padding:0px 8px; border:1px solid {sc}44;
        """)
        self._bat_lbl.setText(f"{robot['battery']}%")
        self._bat_bar.setValue(robot['battery'])
        bc = ERROR if robot['battery'] < 20 else (WARNING if robot['battery'] < 40 else SUCCESS)
        self._bat_bar.setStyleSheet(f"""
            QProgressBar {{ background:#F1F5F9; border-radius:4px; border:none; }}
            QProgressBar::chunk {{ background:{bc}; border-radius:4px; }}
        """)
        self._signal_lbl.setText(robot['signal'])
        self._task_lbl.setText(robot['task'])
        dc = ERROR if robot['damage'] != '정상' else SUCCESS
        self._damage_lbl.setText(robot['damage'])
        self._damage_lbl.setStyleSheet(f"font-size:13px; color:{dc}; background:transparent;")


class BlackboxPlayer(QDialog):
    def __init__(self, robot_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'블랙박스 — {robot_id}')
        self.setMinimumSize(500, 360)
        vl = QVBoxLayout(self); vl.setContentsMargins(20, 16, 20, 16); vl.setSpacing(12)
        vl.addWidget(mklbl(f'로봇 {robot_id} 블랙박스', 16, True))

        screen = QLabel('[ 영상 재생 화면 (시뮬레이션) ]')
        screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        screen.setFixedHeight(200)
        screen.setStyleSheet("background:#0F172A; color:#64748B; border-radius:8px; font-size:14px;")
        vl.addWidget(screen)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100); self.slider.setValue(0)
        vl.addWidget(self.slider)

        ctrl = QHBoxLayout()
        for txt, color in [('⏮ 처음', TEXT2), ('⏪ -10s', TEXT2), ('▶ 재생', PRIMARY),
                           ('⏸ 일시정지', WARNING), ('⏩ +10s', TEXT2)]:
            ctrl.addWidget(mkbtn(txt, color, small=True))
        ctrl.addStretch()
        vl.addLayout(ctrl)

        b_close = mkobtn('닫기'); b_close.clicked.connect(self.close)
        vl.addWidget(b_close, alignment=Qt.AlignmentFlag.AlignRight)


class MonitoringPage(QWidget):
    STATUSES = ['정상대기', '충전중', '에러', '오프라인']
    SIGNALS  = ['양호(5G)', '보통(4G)', '약함(3G)', '없음']
    TASKS    = ['대기 중', '음료 서빙', '복귀 중', '경로 탐색', '충전 중']
    DAMAGES  = ['정상', '정상', '정상', '전면 파손', '좌측 파손']

    def __init__(self):
        super().__init__()
        self.robots = [
            {'id': f'ROB-{i+1:02d}', 'status': '정상대기',
             'battery': random.randint(60, 100),
             'signal': '양호(5G)', 'task': '대기 중', 'damage': '정상'}
            for i in range(3)
        ]
        self.cards = {}
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_data)
        self._timer.start(3000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('실시간 모니터링', '로봇 상태 실시간 확인 및 블랙박스 재생'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(16)
        root.addWidget(body, 1)

        tr = QHBoxLayout()
        b_add = mkbtn('+ 로봇 추가'); b_add.clicked.connect(self._add_robot)
        b_rem = mkbtn('로봇 제거', ERROR); b_rem.clicked.connect(self._remove_robot)
        tr.addWidget(b_add); tr.addWidget(b_rem); tr.addStretch()
        self.summary_lbl = mklbl('', color=TEXT2)
        tr.addWidget(self.summary_lbl)
        bl.addLayout(tr)

        self.cards_widget = QWidget()
        self.cards_widget.setStyleSheet(f"background:{BG};")
        self.cards_lay = QGridLayout(self.cards_widget)
        self.cards_lay.setSpacing(16); self.cards_lay.setContentsMargins(0,0,0,0)
        bl.addWidget(wrap_scroll(self.cards_widget), 1)
        self._rebuild_cards()

        bbcard, bbl = card_frame('블랙박스 재생')
        bbcard.setMaximumHeight(90)
        brow = QHBoxLayout(); brow.setSpacing(10)
        brow.addWidget(mklbl('로봇 선택:', bold=True))
        self.c_robot = QComboBox()
        for r in self.robots: self.c_robot.addItem(r['id'])
        brow.addWidget(self.c_robot)
        b_play = mkbtn('▶ 블랙박스 재생', PURPLE)
        b_play.clicked.connect(self._open_blackbox)
        brow.addWidget(b_play); brow.addStretch()
        bbl.addLayout(brow)
        bl.addWidget(bbcard)

    def _rebuild_cards(self):
        while self.cards_lay.count():
            item = self.cards_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.cards = {}
        for i, r in enumerate(self.robots):
            card = RobotCard(r)
            self.cards[r['id']] = card
            self.cards_lay.addWidget(card, i//3, i%3)
        if hasattr(self, 'c_robot'):
            self.c_robot.clear()
            for r in self.robots: self.c_robot.addItem(r['id'])
        self._update_summary()

    def _update_data(self):
        for r in self.robots:
            if r['status'] == '오프라인': continue
            r['battery'] = max(0, min(100, r['battery'] + random.randint(-2, 1)))
            r['status']  = random.choices(self.STATUSES, weights=[70,15,10,5])[0]
            r['task']    = random.choice(self.TASKS)
            if r['id'] in self.cards:
                self.cards[r['id']].update_data(r)
        self._update_summary()

    def _update_summary(self):
        ok  = sum(1 for r in self.robots if r['status'] == '정상대기')
        err = sum(1 for r in self.robots if r['status'] == '에러')
        off = sum(1 for r in self.robots if r['status'] == '오프라인')
        self.summary_lbl.setText(
            f"전체 {len(self.robots)} | 정상 {ok} | 에러 {err} | 오프라인 {off}")

    def _add_robot(self):
        nid = f'ROB-{len(self.robots)+1:02d}'
        self.robots.append({
            'id': nid, 'status': '오프라인', 'battery': 100,
            'signal': '없음', 'task': '대기 중', 'damage': '정상'
        })
        self._rebuild_cards()

    def _remove_robot(self):
        if not self.robots:
            QMessageBox.information(self, '안내', '제거할 로봇이 없습니다.')
            return
        sel, ok = QInputDialog.getItem(
            self, '로봇 제거', '제거할 로봇:', [r['id'] for r in self.robots], 0, False)
        if ok:
            self.robots = [r for r in self.robots if r['id'] != sel]
            self._rebuild_cards()

    def _open_blackbox(self):
        rid = self.c_robot.currentText()
        if rid:
            BlackboxPlayer(rid, self).exec()


# ═══════════════════════════════════════════════════════════════════
#  PAGE 6 — CONTROL DASHBOARD
# ═══════════════════════════════════════════════════════════════════

class DashboardPage(QWidget):
    MODES = [
        ('대기',     '🕐', '#64748B'),
        ('호객 NPC', '📣', ORANGE),
        ('서빙',     '🤖', PRIMARY),
        ('팔로우',   '🚶', PURPLE),
    ]

    def __init__(self):
        super().__init__()
        self._mode    = '대기'
        self._battery = 87
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('관제 대시보드', '로봇 모드 전환 및 상태 모니터링'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(20)
        root.addWidget(body, 1)

        # Robot selector
        top = QHBoxLayout()
        top.addWidget(mklbl('제어 대상 로봇:', bold=True))
        self.c_robot = QComboBox()
        self.c_robot.addItems(['ROB-01', 'ROB-02', 'ROB-03'])
        top.addWidget(self.c_robot); top.addStretch()
        top.addWidget(mkbadge('연결됨', SUCCESS))
        bl.addLayout(top)

        # Mode buttons
        mcard, ml = card_frame('모드 전환')
        mrow = QHBoxLayout(); mrow.setSpacing(16)
        self._mode_btns = {}
        for name, icon, color in self.MODES:
            b = QPushButton(f"{icon}\n{name}")
            b.setFixedSize(130, 100)
            b.setStyleSheet(self._mode_btn_style(color, name == self._mode))
            b.clicked.connect(lambda checked, n=name, c=color: self._set_mode(n, c))
            self._mode_btns[name] = (b, color)
            mrow.addWidget(b, alignment=Qt.AlignmentFlag.AlignCenter)
        ml.addLayout(mrow)
        bl.addWidget(mcard)

        # Status panel
        scard, sl = card_frame('상태 표시')
        sg = QGridLayout(); sg.setSpacing(16)

        def stat_cell(label, val, color=TEXT):
            w = QWidget(); wl = QVBoxLayout(w)
            wl.setContentsMargins(0,0,0,0); wl.setSpacing(4)
            wl.addWidget(mklbl(label, 11, color=TEXT3))
            lbl = mklbl(val, 16, True, color)
            wl.addWidget(lbl)
            return w, lbl

        w1, self.mode_lbl   = stat_cell('현재 모드', self._mode, PRIMARY)
        w2, self.bat_lbl    = stat_cell('배터리', '87%', SUCCESS)
        w3, self.alarm_lbl  = stat_cell('안전 알람', '없음', SUCCESS)
        w4, self.reject_lbl = stat_cell('Reject 사유', '—', TEXT2)
        sg.addWidget(w1, 0, 0); sg.addWidget(w2, 0, 1)
        sg.addWidget(w3, 0, 2); sg.addWidget(w4, 0, 3)
        sl.addLayout(sg)
        bl.addWidget(scard)

        # Force utterance
        fcard, fl = card_frame('강제 발화')
        fl.addWidget(mklbl(
            '로봇에게 즉시 발화 명령을 전송합니다. (priority=10, preempt=true)', 12, color=TEXT2))

        fr = QFormLayout(); fr.setSpacing(10)
        self.e_utt  = QLineEdit(); self.e_utt.setPlaceholderText('발화 텍스트를 입력하세요...')
        self.e_pri  = QSpinBox(); self.e_pri.setRange(1, 10); self.e_pri.setValue(10)
        self.e_pri.setMaximumWidth(100)
        self.cb_pre = QCheckBox('preempt = true'); self.cb_pre.setChecked(True)
        fr.addRow(mklbl('발화 텍스트', bold=True), self.e_utt)
        fr.addRow(mklbl('Priority',   bold=True), self.e_pri)
        fr.addRow(mklbl('옵션',       bold=True), self.cb_pre)
        fl.addLayout(fr)

        frow = QHBoxLayout(); frow.addStretch()
        b_send = mkbtn('📢 전송', PURPLE)
        b_send.clicked.connect(self._send_utterance)
        frow.addWidget(b_send)
        fl.addLayout(frow)
        bl.addWidget(fcard)
        bl.addStretch()

    def _mode_btn_style(self, color, active):
        if active:
            return f"""
                QPushButton {{
                    background:{color}; color:#fff; border:none;
                    border-radius:12px; font-size:13px; font-weight:700;
                    padding:10px; border:3px solid {color};
                }}
            """
        return f"""
            QPushButton {{
                background:{color}18; color:{color};
                border:2px solid {color}44; border-radius:12px;
                font-size:13px; font-weight:700; padding:10px;
            }}
            QPushButton:hover {{ background:{color}30; }}
        """

    def _set_mode(self, name, color):
        self._mode = name
        self.mode_lbl.setText(name)
        self.mode_lbl.setStyleSheet(
            f"font-size:16px; font-weight:700; color:{color}; background:transparent;")
        for n, (b, c) in self._mode_btns.items():
            b.setStyleSheet(self._mode_btn_style(c, n == name))

    def _tick(self):
        self._battery = max(0, min(100, self._battery + random.randint(-1, 0)))
        bc = ERROR if self._battery < 20 else (WARNING if self._battery < 40 else SUCCESS)
        self.bat_lbl.setText(f"{self._battery}%")
        self.bat_lbl.setStyleSheet(
            f"font-size:16px; font-weight:700; color:{bc}; background:transparent;")
        if self._battery < 20:
            self.alarm_lbl.setText('배터리 부족!')
            self.alarm_lbl.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{ERROR}; background:transparent;")
        else:
            self.alarm_lbl.setText('없음')
            self.alarm_lbl.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{SUCCESS}; background:transparent;")

    def _send_utterance(self):
        txt = self.e_utt.text().strip()
        if not txt:
            QMessageBox.warning(self, '입력 오류', '발화 텍스트를 입력하세요.')
            return
        robot = self.c_robot.currentText()
        pri   = self.e_pri.value()
        pre   = self.cb_pre.isChecked()
        QMessageBox.information(self, '전송 완료',
            f"[{robot}] 발화 전송 완료\n"
            f"텍스트: {txt}\n"
            f"priority: {pri}, preempt: {str(pre).lower()}")
        self.e_utt.clear()
        self.reject_lbl.setText('—')


# ═══════════════════════════════════════════════════════════════════
#  PAGE 7 — SYSTEM LOG
# ═══════════════════════════════════════════════════════════════════

class SystemLogPage(QWidget):
    LEVELS   = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL']
    LEVEL_C  = {'DEBUG': TEXT3, 'INFO': CYAN, 'WARN': WARNING, 'ERROR': ERROR, 'CRITICAL': PURPLE}
    ROBOTS   = ['ROB-01', 'ROB-02', 'ROB-03', 'SYSTEM']
    TABS     = ['task', '주행', '로봇팔', '하드웨어', '인터랙션', '운영자액션']
    MESSAGES = {
        'task':      ['서빙 태스크 시작', '태스크 완료', '태스크 취소됨', '목표 지점 도달', '새 태스크 할당'],
        '주행':      ['경로 계획 중', '장애물 감지', '우회 경로 탐색', '목적지 도착', '주행 중지'],
        '로봇팔':    ['팔 동작 시작', '물체 집기 성공', '물체 놓기 완료', '팔 충돌 감지', '팔 초기화'],
        '하드웨어':  ['배터리 경고', '온도 이상', '카메라 에러', '센서 재시작', '충전 완료'],
        '인터랙션':  ['고객 인식', '주문 수신', '음성 응답', '인터랙션 종료', '호출 감지'],
        '운영자액션':['모드 변경', '강제 발화', '긴급 정지', '로봇 추가', '로봇 제거'],
    }

    def __init__(self):
        super().__init__()
        self._all_logs = []
        self._generate_initial()
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._add_random_log)
        self._timer.start(4000)

    def _generate_initial(self):
        for _ in range(60):
            tab   = random.choice(self.TABS)
            level = random.choices(self.LEVELS, weights=[20,50,15,10,5])[0]
            robot = random.choice(self.ROBOTS)
            msg   = random.choice(self.MESSAGES[tab])
            ts    = datetime.now() - timedelta(seconds=random.randint(0, 3600))
            self._all_logs.append({'ts': ts, 'level': level, 'robot': robot, 'tab': tab, 'msg': msg})
        self._all_logs.sort(key=lambda x: x['ts'], reverse=True)

    def _add_random_log(self):
        tab   = random.choice(self.TABS)
        level = random.choices(self.LEVELS, weights=[20,50,15,10,5])[0]
        robot = random.choice(self.ROBOTS)
        msg   = random.choice(self.MESSAGES[tab])
        self._all_logs.insert(0, {'ts': datetime.now(), 'level': level,
                                  'robot': robot, 'tab': tab, 'msg': msg})
        if len(self._all_logs) > 500:
            self._all_logs.pop()
        self._refresh_current_tab()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('시스템 로그', '로봇 및 시스템 이벤트 로그 조회'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(14)
        root.addWidget(body, 1)

        # Filter bar
        fbar = QHBoxLayout(); fbar.setSpacing(10)
        fbar.addWidget(mklbl('레벨:', bold=True))
        self.c_level = QComboBox(); self.c_level.addItems(['전체'] + self.LEVELS)
        self.c_level.currentTextChanged.connect(self._refresh_current_tab)
        fbar.addWidget(self.c_level)

        fbar.addWidget(mklbl('로봇:', bold=True))
        self.c_robot = QComboBox(); self.c_robot.addItems(['전체'] + self.ROBOTS)
        self.c_robot.currentTextChanged.connect(self._refresh_current_tab)
        fbar.addWidget(self.c_robot)

        fbar.addWidget(mklbl('검색:', bold=True))
        self.e_search = QLineEdit(); self.e_search.setPlaceholderText('메시지 검색...')
        self.e_search.textChanged.connect(self._refresh_current_tab)
        fbar.addWidget(self.e_search, 1)

        b_clr = mkobtn('로그 초기화', ERROR)
        b_clr.clicked.connect(self._clear_logs)
        fbar.addWidget(b_clr)
        bl.addLayout(fbar)

        self.tabs = QTabWidget()
        self.tab_tables = {}
        for tab_name in self.TABS:
            tbl = make_table(['시각', '레벨', '로봇', '메시지'], stretch_last=True)
            tbl.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents)
            tbl.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents)
            tbl.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents)
            self.tab_tables[tab_name] = tbl
            self.tabs.addTab(tbl, tab_name)
        self.tabs.currentChanged.connect(lambda _: self._refresh_current_tab())
        bl.addWidget(self.tabs, 1)
        self._refresh_current_tab()

    def _refresh_current_tab(self):
        tab_name = self.TABS[self.tabs.currentIndex()]
        tbl      = self.tab_tables[tab_name]
        level_f  = self.c_level.currentText()
        robot_f  = self.c_robot.currentText()
        search_f = self.e_search.text().lower()

        logs = [l for l in self._all_logs if l['tab'] == tab_name]
        if level_f != '전체':  logs = [l for l in logs if l['level'] == level_f]
        if robot_f != '전체':  logs = [l for l in logs if l['robot'] == robot_f]
        if search_f:           logs = [l for l in logs if search_f in l['msg'].lower()]

        tbl.setRowCount(0)
        for log in logs[:200]:
            r = tbl.rowCount(); tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(log['ts'].strftime('%H:%M:%S')))
            item_level = QTableWidgetItem(log['level'])
            color = self.LEVEL_C.get(log['level'], TEXT)
            item_level.setForeground(QColor(color))
            item_level.setFont(QFont('', -1, QFont.Weight.Bold))
            tbl.setItem(r, 1, item_level)
            tbl.setItem(r, 2, QTableWidgetItem(log['robot']))
            tbl.setItem(r, 3, QTableWidgetItem(log['msg']))

    def _clear_logs(self):
        if QMessageBox.question(self, '초기화', '모든 로그를 삭제할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self._all_logs.clear()
            for tbl in self.tab_tables.values():
                tbl.setRowCount(0)


# ═══════════════════════════════════════════════════════════════════
#  PAGE 8 — ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════════

class AnomalyPage(QWidget):
    TYPES = {
        '로봇 파손':   (ERROR,   '🔴'),
        '통신 이상':   (WARNING, '🟠'),
        '주행 방해':   (ORANGE,  '🟡'),
        '로봇팔 방해': (PURPLE,  '🟣'),
    }
    ROBOTS = ['ROB-01', 'ROB-02', 'ROB-03']

    def __init__(self):
        super().__init__()
        self._alerts = []
        self._nid = 1
        self._gen_initial()
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._maybe_alert)
        self._timer.start(8000)

    def _gen_initial(self):
        types = list(self.TYPES.keys())
        for _ in range(5):
            atype = random.choice(types)
            ts = datetime.now() - timedelta(minutes=random.randint(1, 60))
            self._alerts.append({
                'id': self._nid, 'type': atype,
                'robot': random.choice(self.ROBOTS),
                'ts': ts, 'acked': False, 'detail': f"{atype} 이벤트 감지됨"
            })
            self._nid += 1
        self._alerts.sort(key=lambda x: x['ts'], reverse=True)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('이상 상태 감지', '로봇 이상 알림 수신 및 확인 처리'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(20)
        root.addWidget(body, 1)

        # Stats
        left = QWidget(); left.setMaximumWidth(200)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(12)
        ll.addWidget(mklbl('감지 현황', 14, True))
        self._stat_cards = {}
        for atype, (color, icon) in self.TYPES.items():
            c, cl = card_frame()
            cl.setSpacing(4)
            cl.addWidget(mklbl(f"{icon} {atype}", 12, True, color))
            cnt = mklbl('0', 26, True, color)
            cl.addWidget(cnt, alignment=Qt.AlignmentFlag.AlignCenter)
            self._stat_cards[atype] = cnt
            ll.addWidget(c)
        ll.addStretch()
        bl.addWidget(left)

        # Alert list
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(12)
        rl.addWidget(mklbl('알림 목록', 14, True))

        tr = QHBoxLayout()
        b_ack = mkbtn('선택 확인 처리', SUCCESS); b_ack.clicked.connect(self._ack_selected)
        b_all = mkbtn('전체 확인', WARNING);      b_all.clicked.connect(self._ack_all)
        b_clr = mkbtn('확인된 항목 삭제', ERROR); b_clr.clicked.connect(self._clear_acked)
        tr.addWidget(b_ack); tr.addWidget(b_all); tr.addWidget(b_clr); tr.addStretch()
        rl.addLayout(tr)

        self.table = make_table(['유형', '로봇', '발생시각', '상세', '상태'])
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        rl.addWidget(self.table, 1)
        bl.addWidget(right, 1)
        self._refresh()

    def _refresh(self):
        for atype in self.TYPES:
            cnt = sum(1 for a in self._alerts if a['type'] == atype and not a['acked'])
            self._stat_cards[atype].setText(str(cnt))

        self.table.setRowCount(0)
        for a in self._alerts:
            r = self.table.rowCount(); self.table.insertRow(r)
            color, icon = self.TYPES[a['type']]
            item_type = QTableWidgetItem(f"{icon} {a['type']}")
            item_type.setForeground(QColor(color))
            item_type.setFont(QFont('', -1, QFont.Weight.Bold))
            self.table.setItem(r, 0, item_type)
            self.table.setItem(r, 1, QTableWidgetItem(a['robot']))
            self.table.setItem(r, 2, QTableWidgetItem(a['ts'].strftime('%m/%d %H:%M:%S')))
            self.table.setItem(r, 3, QTableWidgetItem(a['detail']))
            status = '✅ 확인됨' if a['acked'] else '⚠ 미확인'
            sc = TEXT2 if a['acked'] else ERROR
            item_s = QTableWidgetItem(status)
            item_s.setForeground(QColor(sc))
            self.table.setItem(r, 4, item_s)
            if a['acked']:
                for col in range(5):
                    item = self.table.item(r, col)
                    if item: item.setForeground(QColor(TEXT3))

    def _ack_selected(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, '안내', '확인 처리할 알림을 선택하세요.')
            return
        if not self._alerts[r]['acked']:
            self._alerts[r]['acked'] = True
            self._refresh()

    def _ack_all(self):
        for a in self._alerts: a['acked'] = True
        self._refresh()

    def _clear_acked(self):
        self._alerts = [a for a in self._alerts if not a['acked']]
        self._refresh()

    def _maybe_alert(self):
        if random.random() < 0.35:
            atype = random.choice(list(self.TYPES.keys()))
            new_alert = {
                'id': self._nid, 'type': atype,
                'robot': random.choice(self.ROBOTS),
                'ts': datetime.now(), 'acked': False,
                'detail': f"{atype} 자동 감지됨"
            }
            self._nid += 1
            self._alerts.insert(0, new_alert)
            self._refresh()
            color, icon = self.TYPES[atype]
            msg = QMessageBox(self.window())
            msg.setWindowTitle('⚠ 이상 상태 감지')
            msg.setText(
                f"{icon} {atype}\n"
                f"로봇: {new_alert['robot']}\n"
                f"시각: {new_alert['ts'].strftime('%H:%M:%S')}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            QTimer.singleShot(4000, msg.close)
            msg.show()


# ═══════════════════════════════════════════════════════════════════
#  PAGE 9 — INVENTORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

class InventoryDialog(QDialog):
    UNITS = ['개', 'ml', 'g', 'kg', 'L', '봉지', '박스']

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle('재고 ' + ('수정' if data else '추가'))
        self.setMinimumWidth(360)
        self.data = data or {}
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20); vl.setSpacing(14)
        vl.addWidget(mklbl('재고 정보', 16, True))

        g = QFormLayout(); g.setSpacing(10)
        self.e_name = QLineEdit(self.data.get('name', ''))
        self.e_name.setPlaceholderText('품목명')
        self.e_qty  = QSpinBox(); self.e_qty.setRange(0, 99999)
        self.e_qty.setValue(self.data.get('qty', 0))
        self.c_unit = QComboBox(); self.c_unit.addItems(self.UNITS)
        if self.data.get('unit'): self.c_unit.setCurrentText(self.data['unit'])
        self.e_thr  = QSpinBox(); self.e_thr.setRange(0, 99999)
        self.e_thr.setValue(self.data.get('threshold', 10))
        self.e_thr.setToolTip('이 수량 이하면 부족 경고를 표시합니다')

        g.addRow(mklbl('품목명', bold=True), self.e_name)
        g.addRow(mklbl('수량',   bold=True), self.e_qty)
        g.addRow(mklbl('단위',   bold=True), self.c_unit)
        g.addRow(mklbl('임계값', bold=True), self.e_thr)
        vl.addLayout(g)

        vl.addWidget(hdivider())
        row = QHBoxLayout(); row.addStretch()
        b_cancel = mkobtn('취소'); b_cancel.clicked.connect(self.reject)
        b_ok = mkbtn('저장');     b_ok.clicked.connect(self._submit)
        row.addWidget(b_cancel); row.addWidget(b_ok)
        vl.addLayout(row)

    def _submit(self):
        name = self.e_name.text().strip()
        if not name:
            QMessageBox.warning(self, '입력 오류', '품목명을 입력하세요.')
            return
        self.result_data = {
            'name': name, 'qty': self.e_qty.value(),
            'unit': self.c_unit.currentText(),
            'threshold': self.e_thr.value(),
        }
        self.accept()


class InventoryPage(QWidget):
    def __init__(self):
        super().__init__()
        self.items = [
            {'id':1,'name':'에스프레소 원두','qty':120,'unit':'g','threshold':50},
            {'id':2,'name':'우유',           'qty':8,  'unit':'L','threshold':5},
            {'id':3,'name':'시럽 (바닐라)',  'qty':3,  'unit':'개','threshold':5},
            {'id':4,'name':'일회용 컵 (M)',  'qty':200,'unit':'개','threshold':50},
            {'id':5,'name':'일회용 컵 (L)',  'qty':150,'unit':'개','threshold':30},
            {'id':6,'name':'빨대',           'qty':80, 'unit':'개','threshold':50},
            {'id':7,'name':'얼음',           'qty':15, 'unit':'kg','threshold':10},
            {'id':8,'name':'저지방 우유',    'qty':2,  'unit':'L','threshold':3},
        ]
        self._nid = 9
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(page_header('재고 관리', '음료 재료 및 소모품 재고 수량 관리'))

        body = QWidget(); body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(16)
        root.addWidget(body, 1)

        # Summary cards
        stats = QHBoxLayout(); stats.setSpacing(12)
        total = len(self.items)
        low   = sum(1 for i in self.items if i['qty'] <= i['threshold'])
        for label, value, color in [
            ('전체 품목', str(total), PRIMARY),
            ('정상',     str(total-low), SUCCESS),
            ('부족/주의', str(low), ERROR),
        ]:
            sc, sl = card_frame()
            sl.setSpacing(4)
            sl.addWidget(mklbl(label, 12, color=TEXT2))
            sl.addWidget(mklbl(value, 28, True, color))
            sc.setMinimumWidth(120); sc.setMaximumHeight(90)
            stats.addWidget(sc)
        stats.addStretch()
        bl.addLayout(stats)

        # Toolbar
        tr = QHBoxLayout()
        b_add   = mkbtn('+ 품목 추가'); b_add.clicked.connect(self._add)
        b_edit  = mkbtn('수정', WARNING); b_edit.clicked.connect(self._edit)
        b_del   = mkbtn('삭제', ERROR);   b_del.clicked.connect(self._delete)
        b_plus  = mkbtn('수량 +', SUCCESS, small=True)
        b_plus.clicked.connect(lambda: self._adjust(1))
        b_minus = mkbtn('수량 -', ORANGE, small=True)
        b_minus.clicked.connect(lambda: self._adjust(-1))
        tr.addWidget(b_add); tr.addWidget(b_edit); tr.addWidget(b_del)
        tr.addWidget(b_plus); tr.addWidget(b_minus)
        tr.addStretch()
        bl.addLayout(tr)

        self.table = make_table(['품목명', '수량', '단위', '임계값', '상태'])
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        bl.addWidget(self.table, 1)
        self._refresh()

    def _refresh(self):
        self.table.setRowCount(0)
        for item in self.items:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(item['name']))
            qty_item = QTableWidgetItem(str(item['qty']))
            low = item['qty'] <= item['threshold']
            if low:
                qty_item.setForeground(QColor(ERROR))
                qty_item.setFont(QFont('', -1, QFont.Weight.Bold))
            self.table.setItem(r, 1, qty_item)
            self.table.setItem(r, 2, QTableWidgetItem(item['unit']))
            self.table.setItem(r, 3, QTableWidgetItem(str(item['threshold'])))
            status_item = QTableWidgetItem('⚠ 부족' if low else '✅ 정상')
            status_item.setForeground(QColor(ERROR if low else SUCCESS))
            self.table.setItem(r, 4, status_item)

    def _selected(self):
        r = self.table.currentRow()
        return self.items[r] if r >= 0 else None

    def _add(self):
        dlg = InventoryDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_data; d['id'] = self._nid
            self._nid += 1; self.items.append(d); self._refresh()

    def _edit(self):
        item = self._selected()
        if not item:
            QMessageBox.information(self, '안내', '수정할 품목을 선택하세요.')
            return
        dlg = InventoryDialog(self, item)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item.update(dlg.result_data); self._refresh()

    def _delete(self):
        item = self._selected()
        if not item:
            QMessageBox.information(self, '안내', '삭제할 품목을 선택하세요.')
            return
        if QMessageBox.question(self, '삭제 확인',
            f"'{item['name']}' 항목을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.items.remove(item); self._refresh()

    def _adjust(self, delta):
        item = self._selected()
        if not item:
            QMessageBox.information(self, '안내', '수량을 조정할 품목을 선택하세요.')
            return
        amount, ok = QInputDialog.getInt(
            self, '수량 조정',
            f"'{item['name']}' {'추가' if delta>0 else '차감'} 수량 입력 "
            f"(현재: {item['qty']} {item['unit']}):",
            1, 1, 9999)
        if ok:
            item['qty'] = max(0, item['qty'] + delta * amount)
            self._refresh()


# ═══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════

class Sidebar(QWidget):
    page_changed = pyqtSignal(int)

    NAV_ITEMS = [
        ('🗺', '지도 관리'),
        ('👤', '관리자 정보'),
        ('🔑', '권한 관리'),
        ('🥤', '메뉴 관리'),
        ('📡', '실시간 모니터링'),
        ('🎮', '관제 대시보드'),
        ('📋', '시스템 로그'),
        ('⚠',  '이상 감지'),
        ('📦', '재고 관리'),
    ]

    def __init__(self):
        super().__init__()
        self.setFixedWidth(220)
        self.setStyleSheet(f"background:{SIDEBAR};")
        self._btns = []
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Logo
        logo = QWidget()
        logo.setFixedHeight(70)
        logo.setStyleSheet(f"background:{SIDEBAR}; border-bottom:1px solid #2D3F5A;")
        ll = QVBoxLayout(logo); ll.setContentsMargins(20, 16, 20, 14)
        title = QLabel('🤖 Robot Admin')
        title.setStyleSheet("color:#fff; font-size:15px; font-weight:800; background:transparent;")
        ll.addWidget(title)
        vl.addWidget(logo)

        # Nav buttons
        nav = QWidget(); nav.setStyleSheet(f"background:{SIDEBAR};")
        nl = QVBoxLayout(nav); nl.setContentsMargins(10, 12, 10, 12); nl.setSpacing(4)

        for i, (icon, label) in enumerate(self.NAV_ITEMS):
            b = QPushButton(f"  {icon}  {label}")
            b.setFixedHeight(44)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setStyleSheet(self._btn_style(i == 0))
            b.clicked.connect(lambda checked, idx=i: self._nav(idx))
            self._btns.append(b)
            nl.addWidget(b)

        nl.addStretch()
        vl.addWidget(nav, 1)

        # Footer
        footer = QWidget()
        footer.setFixedHeight(56)
        footer.setStyleSheet(f"background:#111B2E; border-top:1px solid #2D3F5A;")
        fl = QHBoxLayout(footer); fl.setContentsMargins(16, 10, 16, 10)
        ver = QLabel('v2.0.0 — PyQt6')
        ver.setStyleSheet("color:#475569; font-size:11px; background:transparent;")
        fl.addWidget(ver); fl.addStretch()
        vl.addWidget(footer)

    def _btn_style(self, active):
        if active:
            return f"""
                QPushButton {{
                    background:{SB_ACT}; color:#fff;
                    border:none; border-radius:8px;
                    font-size:13px; font-weight:700;
                    text-align:left; padding-left:4px;
                }}
            """
        return f"""
            QPushButton {{
                background:transparent; color:#94A3B8;
                border:none; border-radius:8px;
                font-size:13px; font-weight:500;
                text-align:left; padding-left:4px;
            }}
            QPushButton:hover {{ background:{SB_HV}; color:#fff; }}
        """

    def _nav(self, idx):
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._btn_style(i == idx))
        self.page_changed.emit(idx)


# ═══════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Robot Service Admin GUI — PyQt6')
        self.setMinimumSize(1280, 780)
        self._build()

    def _build(self):
        central = QWidget()
        central.setObjectName('root')
        central.setStyleSheet(f"QWidget#root{{background:{BG};}}")
        self.setCentralWidget(central)

        hl = QHBoxLayout(central)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self._switch_page)
        hl.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{BG};")

        for page in [
            MapManagementPage(),
            AdminInfoPage(),
            PermissionPage(),
            MenuPage(),
            MonitoringPage(),
            DashboardPage(),
            SystemLogPage(),
            AnomalyPage(),
            InventoryPage(),
        ]:
            self.stack.addWidget(page)

        hl.addWidget(self.stack, 1)

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)

