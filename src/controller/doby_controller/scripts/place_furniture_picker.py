#!/usr/bin/env python3
"""place_furniture_picker.py — mapv5_mocamap 위에 가구를 클릭으로 배치.

대상 가구:
  prep_station, open_arm, kiosk, pinky_home, pinky_spawn, T01~T05 (5개 테이블),
  B01~B05 (5개 광고 배너 — roll-up 자립형, +x = 광고면),
  L01~L05 (5개 스탠드형 전등 — floor_lamp 모델, 갓 안 warm point light),
  P01~P05 (5개 분재 — bonsai_tree 모델, 화분 + 잎 클러스터)

좌표계: mapv5_mocamap.yaml — origin (-51.320, -6.624, 0), 0.05 m/px, 391×250.
캔버스 = 3x upscale (1173×750).

조작:
  - 좌측 리스트에서 가구 선택
  - 맵 좌측 클릭 = 그 좌표에 배치 (yaw 는 슬라이더 값)
  - yaw 슬라이더 또는 0/±90/180 버튼
  - Save YAML → config/cafe_layout.yaml
  - Export .world snippet → SDF <include> 출력

산출물:
  config/cafe_layout.yaml — furniture/tables 분리 저장
"""
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import yaml
from PIL import Image, ImageTk

REPO = Path(__file__).resolve().parent.parent
MAP_PGM = REPO / "maps" / "mapv5_mocamap.pgm"
DEFAULT_OUT = REPO / "config" / "cafe_layout.yaml"

RES = 0.05
OX, OY = -51.320, -6.624
SCALE = 3

# (sx_m, sy_m, color, z_offset, label, sdf_model)
FURNITURE = {
    "prep_station": dict(size=(1.2, 0.6),  color="#dc1e1e", z=0.0,
                         label="prep_station", model="prep_station"),
    "open_arm":     dict(size=(0.15, 0.15),color="#e68200", z=0.89,
                         label="OpenARM",      model="open_arm"),
    "kiosk":        dict(size=(0.5, 0.4),  color="#00bcd4", z=0.0,
                         label="kiosk",        model="kiosk"),
    "pinky_home":   dict(size=(0.5, 0.4),  color="#9c27b0", z=0.0,
                         label="vicpinky_home", model="vicpinky_home"),
    "pinky_spawn":  dict(size=(0.36, 0.31),color="#28a040", z=0.3,
                         label="pinky_spawn",  model=None),  # spawn pose, no model
    "T01": dict(size=(0.7, 0.7), color="#1e50dc", z=0.0, label="T01", model="cafe_table"),
    "T02": dict(size=(0.7, 0.7), color="#1e50dc", z=0.0, label="T02", model="cafe_table"),
    "T03": dict(size=(0.7, 0.7), color="#1e50dc", z=0.0, label="T03", model="cafe_table"),
    "T04": dict(size=(0.7, 0.7), color="#1e50dc", z=0.0, label="T04", model="cafe_table"),
    "T05": dict(size=(0.7, 0.7), color="#1e50dc", z=0.0, label="T05", model="cafe_table"),
    # T01_wp~T05_wp: robot 정차 waypoint (가구 옆 통로). model=None (Gazebo spawn X — 좌표만).
    # tables.yaml SoT 와 sync — dispatcher / floorplan-view 의 마커 위치.
    "T01_wp": dict(size=(0.36, 0.31), color="#ff007a", z=0.0, label="T01_wp", model=None),
    "T02_wp": dict(size=(0.36, 0.31), color="#ff007a", z=0.0, label="T02_wp", model=None),
    "T03_wp": dict(size=(0.36, 0.31), color="#ff007a", z=0.0, label="T03_wp", model=None),
    "T04_wp": dict(size=(0.36, 0.31), color="#ff007a", z=0.0, label="T04_wp", model=None),
    "T05_wp": dict(size=(0.36, 0.31), color="#ff007a", z=0.0, label="T05_wp", model=None),
    # B01~B05: roll-up 자립 배너 — foot 0.40 x 1.00, +x = 광고면
    "B01": dict(size=(0.4, 1.0), color="#ff7043", z=0.0, label="B01", model="banner"),
    "B02": dict(size=(0.4, 1.0), color="#ff7043", z=0.0, label="B02", model="banner"),
    "B03": dict(size=(0.4, 1.0), color="#ff7043", z=0.0, label="B03", model="banner"),
    "B04": dict(size=(0.4, 1.0), color="#ff7043", z=0.0, label="B04", model="banner"),
    "B05": dict(size=(0.4, 1.0), color="#ff7043", z=0.0, label="B05", model="banner"),
    # L01~L05: 스탠드형 전등 — base d0.40, h~1.74m. 갓 안 warm point light 내장.
    "L01": dict(size=(0.4, 0.4), color="#ffb000", z=0.0, label="L01_lamp", model="floor_lamp"),
    "L02": dict(size=(0.4, 0.4), color="#ffb000", z=0.0, label="L02_lamp", model="floor_lamp"),
    "L03": dict(size=(0.4, 0.4), color="#ffb000", z=0.0, label="L03_lamp", model="floor_lamp"),
    "L04": dict(size=(0.4, 0.4), color="#ffb000", z=0.0, label="L04_lamp", model="floor_lamp"),
    "L05": dict(size=(0.4, 0.4), color="#ffb000", z=0.0, label="L05_lamp", model="floor_lamp"),
    # P01~P05: 분재 — 화분 d0.30, h~0.50m. 바닥/테이블 모두 가능.
    "P01": dict(size=(0.3, 0.3), color="#2e8b57", z=0.0, label="P01_bonsai", model="bonsai_tree"),
    "P02": dict(size=(0.3, 0.3), color="#2e8b57", z=0.0, label="P02_bonsai", model="bonsai_tree"),
    "P03": dict(size=(0.3, 0.3), color="#2e8b57", z=0.0, label="P03_bonsai", model="bonsai_tree"),
    "P04": dict(size=(0.3, 0.3), color="#2e8b57", z=0.0, label="P04_bonsai", model="bonsai_tree"),
    "P05": dict(size=(0.3, 0.3), color="#2e8b57", z=0.0, label="P05_bonsai", model="bonsai_tree"),
    # gate1/gate2/gate3: 매장 출입구 entry point. model=None (Gazebo spawn X — 좌표만).
    # engaging BT 의 사람 감지 ROI anchor + floorplan 시각 표시.
    # size = (yaw 방향 두께, 문 폭). long edge 가 yaw 수직 (banner 패턴 정합).
    # yaw 방향 = 안→밖 (가게 안에서 밖 보는 방향).
    "gate1": dict(size=(0.2, 0.9), color="#00ced1", z=0.0, label="gate1", model=None),
    "gate2": dict(size=(0.2, 0.9), color="#00ced1", z=0.0, label="gate2", model=None),
    "gate3": dict(size=(0.2, 0.9), color="#00ced1", z=0.0, label="gate3", model=None),
}
ORDER = ["prep_station", "open_arm", "kiosk", "pinky_home", "pinky_spawn",
         "T01", "T02", "T03", "T04", "T05",
         "T01_wp", "T02_wp", "T03_wp", "T04_wp", "T05_wp",
         "B01", "B02", "B03", "B04", "B05",
         "L01", "L02", "L03", "L04", "L05",
         "P01", "P02", "P03", "P04", "P05",
         "gate1", "gate2", "gate3"]


class PickerApp:
    def __init__(self, root):
        self.root = root
        root.title("moca furniture picker — mapv5_mocamap")

        img = Image.open(MAP_PGM).convert("RGB")
        self.W_px, self.H_px = img.size
        img_up = img.resize((self.W_px * SCALE, self.H_px * SCALE), Image.NEAREST)
        self.tkimg = ImageTk.PhotoImage(img_up)

        self.placements = {}  # name -> (x, y, yaw)
        self.placement_shapes = {}  # name -> [canvas item ids]

        main = tk.Frame(root)
        main.pack(fill=tk.BOTH, expand=True)

        cframe = tk.Frame(main)
        cframe.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cw = min(1200, img_up.width)
        ch = min(820, img_up.height)
        self.canvas = tk.Canvas(cframe, width=cw, height=ch,
                                scrollregion=(0, 0, img_up.width, img_up.height),
                                bg="#fff", cursor="crosshair")
        hsb = tk.Scrollbar(cframe, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vsb = tk.Scrollbar(cframe, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.config(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tkimg)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)

        self.draw_grid()

        rp = tk.Frame(main, width=280)
        rp.pack(side=tk.RIGHT, fill=tk.Y, padx=8, pady=8)
        rp.pack_propagate(False)

        tk.Label(rp, text="Place furniture", font=("Sans", 12, "bold")).pack(pady=4)
        # exportselection=False — 다른 위젯이 selection 가로채는 것 방지
        self.lst = tk.Listbox(rp, height=18, font=("Mono", 10),
                              exportselection=False)
        self.lst.pack(fill=tk.X)
        self.lst.bind("<<ListboxSelect>>", lambda e: self.refresh())
        self.refresh_listbox()
        self.lst.select_set(0)
        self.lst.activate(0)

        yaw_fr = tk.LabelFrame(rp, text="yaw (rad)")
        yaw_fr.pack(fill=tk.X, pady=8)
        self.yaw_var = tk.DoubleVar(value=0.0)
        tk.Scale(yaw_fr, from_=-math.pi, to=math.pi, resolution=0.01,
                 variable=self.yaw_var, orient=tk.HORIZONTAL,
                 command=lambda _: self.refresh_overlay()).pack(fill=tk.X)
        btns = tk.Frame(yaw_fr); btns.pack()
        for lbl, v in [("0", 0.0), ("90°", math.pi/2),
                        ("180°", math.pi), ("-90°", -math.pi/2)]:
            tk.Button(btns, text=lbl,
                      command=lambda v=v: (self.yaw_var.set(v),
                                            self.refresh_overlay())).pack(side=tk.LEFT)

        info = tk.LabelFrame(rp, text="info")
        info.pack(fill=tk.X, pady=8)
        self.info_lbl = tk.Label(info, text="-", justify=tk.LEFT, anchor=tk.W,
                                  font=("Mono", 9))
        self.info_lbl.pack(fill=tk.X, padx=4)
        self.cursor_lbl = tk.Label(info, text="cursor: -", justify=tk.LEFT,
                                    anchor=tk.W, fg="#666", font=("Mono", 9))
        self.cursor_lbl.pack(fill=tk.X, padx=4)

        bfr = tk.Frame(rp); bfr.pack(fill=tk.X, pady=8)
        tk.Button(bfr, text="Load YAML",
                  command=self.load_yaml_dialog).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(bfr, text="Save YAML",
                  command=self.save_yaml).pack(side=tk.LEFT, expand=True, fill=tk.X)
        bfr2 = tk.Frame(rp); bfr2.pack(fill=tk.X)
        tk.Button(bfr2, text="Clear current (X)",
                  command=self.clear_current).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(bfr2, text="Deselect (ESC)",
                  command=self.deselect).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(rp, text="Export .world snippet",
                  command=self.export_world).pack(fill=tk.X, pady=4)

        # 단축키: X = 현재 배치 삭제, ESC = 가구 선택 해제, 우클릭 = 그 위치의 가구 삭제
        root.bind("<Escape>", lambda e: self.deselect())
        root.bind("<x>", lambda e: self.clear_current())
        root.bind("<X>", lambda e: self.clear_current())
        self.canvas.bind("<Button-3>", self.on_right_click)

        tk.Label(rp,
                 text=f"map: {self.W_px}×{self.H_px} px\n"
                       f"origin: ({OX}, {OY})\n"
                       f"res: {RES} m/px\n"
                       f"out: {DEFAULT_OUT.relative_to(REPO)}",
                 fg="#666", font=("Mono", 8), justify=tk.LEFT, anchor=tk.W).pack(
            fill=tk.X, pady=8)

        if DEFAULT_OUT.exists():
            try:
                self.load_yaml(DEFAULT_OUT)
            except Exception as e:
                print(f"load existing failed: {e}")

        self.refresh()

    # ---- coord transforms ----
    def canvas_to_world(self, cx, cy):
        col = cx / SCALE
        row = cy / SCALE
        wx = OX + col * RES
        wy = OY + (self.H_px - row) * RES
        return wx, wy

    def world_to_canvas(self, wx, wy):
        col = (wx - OX) / RES
        row = self.H_px - (wy - OY) / RES
        return col * SCALE, row * SCALE

    # ---- drawing ----
    def draw_grid(self):
        for wx in range(int(OX), int(OX + self.W_px * RES) + 2):
            cx, _ = self.world_to_canvas(wx, OY)
            self.canvas.create_line(cx, 0, cx, self.H_px * SCALE,
                                    fill="#cce", dash=(2, 4))
            if wx % 5 == 0:
                self.canvas.create_text(cx + 3, 4, anchor=tk.NW,
                                        text=f"x={wx}",
                                        fill="#669", font=("Sans", 7))
        for wy in range(int(OY), int(OY + self.H_px * RES) + 2):
            _, cy = self.world_to_canvas(OX, wy)
            self.canvas.create_line(0, cy, self.W_px * SCALE, cy,
                                    fill="#cce", dash=(2, 4))
            if wy % 5 == 0:
                self.canvas.create_text(4, cy + 2, anchor=tk.NW,
                                        text=f"y={wy}",
                                        fill="#669", font=("Sans", 7))

    def current_name(self):
        sel = self.lst.curselection()
        if sel:
            return ORDER[sel[0]]
        # selection 이 비었을 때 ACTIVE 인덱스 폴백 (Button 클릭 후에도 유효)
        try:
            idx = int(self.lst.index(tk.ACTIVE))
            if 0 <= idx < len(ORDER):
                return ORDER[idx]
        except Exception:
            pass
        return None

    def refresh(self):
        name = self.current_name()
        if not name:
            return
        info = FURNITURE[name]
        if name in self.placements:
            x, y, yaw = self.placements[name]
            self.yaw_var.set(yaw)
            pose_txt = f"x={x:.3f}  y={y:.3f}  yaw={yaw:.3f}"
        else:
            pose_txt = "(not placed)\nclick on map"
        self.info_lbl.config(
            text=f"name: {info['label']}\n"
                  f"size: {info['size'][0]:.2f}×{info['size'][1]:.2f} m\n"
                  f"z: {info['z']}\n"
                  f"pose:\n  {pose_txt}")
        self.refresh_listbox()
        self.refresh_overlay()

    def refresh_listbox(self):
        cur = self.lst.curselection()
        self.lst.delete(0, tk.END)
        for k in ORDER:
            mark = "✓" if k in self.placements else " "
            self.lst.insert(tk.END, f" {mark} {FURNITURE[k]['label']}")
        if cur:
            self.lst.select_set(cur[0])
            self.lst.activate(cur[0])

    def refresh_overlay(self):
        for ids in self.placement_shapes.values():
            for i in ids:
                self.canvas.delete(i)
        self.placement_shapes.clear()
        cur = self.current_name()
        for name, (x, y, yaw) in self.placements.items():
            ids = self.draw_footprint(name, x, y, yaw,
                                       highlight=(name == cur))
            self.placement_shapes[name] = ids

    def draw_footprint(self, name, x, y, yaw, highlight=False):
        info = FURNITURE[name]
        sx_m, sy_m = info["size"]
        color = info["color"]
        cx, cy = self.world_to_canvas(x, y)
        hx_m, hy_m = sx_m / 2, sy_m / 2
        corners = [(hx_m, hy_m), (hx_m, -hy_m), (-hx_m, -hy_m), (-hx_m, hy_m)]
        c, s = math.cos(yaw), math.sin(yaw)
        pts = []
        for dx, dy in corners:
            rwx = dx * c - dy * s
            rwy = dx * s + dy * c
            cox = rwx / RES * SCALE
            coy = -rwy / RES * SCALE  # canvas Y flip
            pts.extend([cx + cox, cy + coy])
        # heading arrow — world +X 방향
        ahx = hx_m * 1.4
        rwx = ahx * c
        rwy = ahx * s
        ahead_cx = cx + rwx / RES * SCALE
        ahead_cy = cy - rwy / RES * SCALE
        width = 3 if highlight else 2
        a = self.canvas.create_polygon(*pts, outline=color, fill="",
                                        width=width)
        b = self.canvas.create_line(cx, cy, ahead_cx, ahead_cy,
                                     fill=color, width=2, arrow=tk.LAST)
        c2 = self.canvas.create_text(cx + 6, cy - 14, anchor=tk.NW,
                                      text=info["label"], fill=color,
                                      font=("Sans", 8, "bold"))
        return [a, b, c2]

    # ---- events ----
    def on_motion(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        wx, wy = self.canvas_to_world(cx, cy)
        self.cursor_lbl.config(text=f"cursor: x={wx:+.2f}  y={wy:+.2f}")

    def on_click(self, event):
        name = self.current_name()
        if not name:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        wx, wy = self.canvas_to_world(cx, cy)
        yaw = float(self.yaw_var.get())
        self.placements[name] = (wx, wy, yaw)
        sel = self.lst.curselection()
        if sel and sel[0] < len(ORDER) - 1:
            self.lst.select_clear(0, tk.END)
            self.lst.select_set(sel[0] + 1)
        self.refresh()

    def clear_current(self):
        name = self.current_name()
        if name and name in self.placements:
            del self.placements[name]
            self.refresh()

    def deselect(self):
        """가구 선택 해제 — 클릭해도 배치 안 됨 (선택 모드 끔)."""
        self.lst.selection_clear(0, tk.END)
        self.info_lbl.config(text="(no furniture selected)\n"
                                   "리스트에서 다시 선택하세요")
        # 강조 outline 만 다시 그리기 위해 overlay refresh
        self.refresh_overlay()

    def on_right_click(self, event):
        """클릭 위치 근처에 배치된 가구가 있으면 삭제."""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        wx, wy = self.canvas_to_world(cx, cy)
        # 가장 가까운 placement 찾기 (footprint 안에 있는지)
        for name, (x, y, _yaw) in list(self.placements.items()):
            sx_m, sy_m = FURNITURE[name]["size"]
            if abs(wx - x) <= sx_m / 2 and abs(wy - y) <= sy_m / 2:
                del self.placements[name]
                self.refresh()
                return

    # ---- yaml I/O ----
    def save_yaml(self, path=None):
        if path is None:
            path = DEFAULT_OUT
        path = Path(path)
        out = {
            "map": {"image": "mapv5_mocamap.pgm", "resolution": RES,
                    "origin": [OX, OY, 0.0]},
            "furniture": {},
            "tables": {},
            "waypoints": {},
            "gates": {},
            "banners": {},
            "lights": {},
            "plants": {},
        }
        for name in ORDER:
            if name not in self.placements:
                continue
            x, y, yaw = self.placements[name]
            row = {"x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 3),
                   "z": FURNITURE[name]["z"]}
            # _wp suffix → waypoints (robot 정차 좌표, model=None)
            if name.endswith("_wp"):
                out["waypoints"][name] = row
            elif name.startswith("gate"):
                out["gates"][name] = row
            elif name.startswith("T"):
                out["tables"][name] = row
            elif name.startswith("B"):
                out["banners"][name] = row
            elif name.startswith("L"):
                out["lights"][name] = row
            elif name.startswith("P"):
                out["plants"][name] = row
            else:
                out["furniture"][name] = row
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
        messagebox.showinfo("saved", f"wrote → {path}")

    def load_yaml_dialog(self):
        p = filedialog.askopenfilename(initialdir=str(DEFAULT_OUT.parent),
                                       filetypes=[("YAML", "*.yaml *.yml")])
        if p:
            self.load_yaml(Path(p))
            self.refresh()

    def load_yaml(self, path):
        data = yaml.safe_load(Path(path).read_text()) or {}
        for sect in ("furniture", "tables", "waypoints", "gates", "banners", "lights", "plants"):
            for k, v in (data.get(sect) or {}).items():
                if k in FURNITURE:
                    self.placements[k] = (float(v["x"]), float(v["y"]),
                                           float(v.get("yaw", 0.0)))

    def export_world(self):
        lines = ["<!-- generated by scripts/place_furniture_picker.py -->"]
        for name in ORDER:
            if name not in self.placements:
                continue
            x, y, yaw = self.placements[name]
            z = FURNITURE[name]["z"]
            model = FURNITURE[name]["model"]
            if model is None:
                lines.append(
                    f"<!-- {name}: spawn pose only — x={x:.3f} y={y:.3f} "
                    f"yaw={yaw:.3f} -->")
                continue
            lines.append(
                f'<include><name>{name}</name>'
                f'<uri>model://{model}</uri>'
                f'<pose>{x:.3f} {y:.3f} {z} 0 0 {yaw:.3f}</pose></include>')
        out = "\n".join(lines)
        win = tk.Toplevel(self.root)
        win.title("world snippet — 복사해서 .world 에 붙여넣기")
        t = tk.Text(win, width=88, height=18, font=("Mono", 9))
        t.insert("1.0", out)
        t.pack(fill=tk.BOTH, expand=True)


def main():
    root = tk.Tk()
    PickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
