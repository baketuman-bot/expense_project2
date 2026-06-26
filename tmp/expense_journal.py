"""
経費精算 仕訳入力ツール
"""
import os, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
from PIL import Image, ImageTk
import fitz

EXCEL_PATH     = r"C:\Users\ai_user\Desktop\koga‗auto\expense_db.v_documentcontents_0623.xlsx"
VOUCHER_DIR    = r"C:\Users\ai_user\Desktop\koga‗auto\証憑ファイル"
HOJO_MASTER    = r"C:\Users\ai_user\Desktop\koga‗auto\補助科目CD.xlsx"
ZEIKUNN_MASTER = r"C:\Users\ai_user\Desktop\koga‗auto\税区分.xlsx"

TAX_RATE_OPTIONS = ["対象外", "8%", "10%"]

BUMON_CS_KBN = {
    "11000":"83","11400":"84","11430":"84","12000":"83","13000":"83",
    "19100":"83","19400":"83","19700":"84","21000":"83","21101":"83",
    "21102":"83","21200":"83","21210":"83","21300":"83","21410":"84",
    "22102":"83","23000":"83","23101":"83","23102":"83","23200":"83",
    "25101":"83","25102":"83","25200":"83","25301":"83","29100":"84",
    "29200":"83","29210":"83","29220":"83","29300":"84","29320":"84",
    "29400":"83","29410":"83","29500":"83","29610":"84","29620":"84",
    "29630":"84","29640":"84","29650":"84","29660":"84","29700":"84",
    "29800":"84","31000":"83","31100":"83","31300":"83","61100":"83",
    "73200":"83","73300":"83","73600":"83","90100":"83","90110":"83",
    "90120":"83","90200":"83","90210":"83","90220":"83","91000":"84",
    "91030":"84","91050":"84","91110":"84","91120":"84","91300":"84",
    "91500":"84","91600":"84","91700":"84","91710":"84","91900":"84",
    "92000":"84","92020":"84","92030":"84","92040":"84","92100":"84",
    "92110":"84","92120":"84","92130":"84","92140":"84","92200":"84",
    "92210":"84","92400":"84","92410":"84","92500":"84","92600":"84",
    "92700":"84","92900":"84","93200":"84","93400":"84","97400":"84",
}

def build_account_cd(account_cd, bumon_cd):
    cd = str(account_cd).strip()
    ln = len(cd)
    if ln == 5: return cd
    if ln == 4: return "8" + cd
    if ln == 3:
        return BUMON_CS_KBN.get(str(bumon_cd).strip(), "??") + cd
    return cd

def load_zeikunn_master(path):
    try:
        df = pd.read_excel(path, dtype=str)
        labels, mapping = [], {}
        for _, row in df.iterrows():
            cd  = str(row.get("税区分コード","")).strip()
            abr = str(row.get("税区分略称","")).strip()
            if abr and abr not in mapping:
                labels.append(abr)
                mapping[abr] = cd
        return labels, mapping
    except Exception as e:
        messagebox.showerror("マスタ読込エラー", f"税区分マスタの読込に失敗しました:\n{e}")
        return [], {}

def load_hojo_master(path):
    try:
        df = pd.read_excel(path, dtype=str)
        master = {}
        for _, row in df.iterrows():
            acd = str(row.get("科目コード","")).strip()
            scd = str(row.get("補助コード","")).strip()
            snm = str(row.get("補助科目名","")).strip()
            if acd:
                master.setdefault(acd, []).append((scd, snm))
        return master
    except Exception as e:
        messagebox.showerror("マスタ読込エラー", f"補助科目マスタの読込に失敗しました:\n{e}")
        return {}

LIST_COLS = [
    ("No","No",40),("date","日付",85),("applicant_name","申請者",90),
    ("account_name","科目",80),("amount","金額",65),
    ("purpose","摘要",110),("_status","状態",55),
]
MANUAL_FIELDS = [
    ("sub_cd","補助科目ｺｰﾄﾞ"),("sub_name","補助科目名"),
    ("tax_amt","税金額"),("tax_kbn","税区分"),("tax_rate","税率"),
    ("fx_rate","換算ﾚｰﾄ"),("fx_tax","外貨税額"),
]
REF_FIELDS = [
    ("applicant_name","申請者"),("date","日付"),
    ("bumon_cd","部門ｺｰﾄﾞ"),("bumon_name","部門名"),
    ("account_cd","科目ｺｰﾄﾞ"),("account_name","科目名"),
    ("amount","税抜金額"),("tsuka_cd","外貨ｺｰﾄﾞ"),
    ("purpose","摘要（品名）"),("shiharaisaki","支払先"),
]

def load_fns_data(path):
    df = pd.read_excel(path, dtype=str)
    df = df[df["status_cd_id"] == "FNS"].copy().reset_index(drop=True)
    df["_row_no"] = range(1, len(df)+1)
    return df

class ExpenseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("経費精算 仕訳入力ツール")
        self.geometry("1400x760")
        self.minsize(1100, 600)
        self.df = pd.DataFrame()
        self.manual_data = {}
        self.current_idx = -1
        self.voucher_files = []
        self.pdf_doc = None
        self.pdf_page_no = 0
        self.photo_img = None
        self.zoom_level = 1.0
        self.hojo_master = {}
        self.zeikunn_labels  = []
        self.zeikunn_mapping = {}
        self._build_ui()
        self._load_vouchers()
        self._load_hojo()
        self._load_zeikunn()
        self._load_data()

    def _load_hojo(self):
        self.hojo_master = load_hojo_master(HOJO_MASTER)

    def _load_zeikunn(self):
        self.zeikunn_labels, self.zeikunn_mapping = load_zeikunn_master(ZEIKUNN_MASTER)
        if hasattr(self, "tax_kbn_combo"):
            self.tax_kbn_combo.configure(values=self.zeikunn_labels)

    def _get_hojo_options(self, raw_account_cd):
        entries = self.hojo_master.get(str(raw_account_cd).strip(), [])
        labels  = [f"{cd}　{nm}" for cd, nm in entries]
        mapping = {f"{cd}　{nm}": (cd, nm) for cd, nm in entries}
        return labels, mapping

    # ─── UI構築 ───
    def _build_ui(self):
        self.configure(bg="#f0f0f0")
        tb = tk.Frame(self, bg="#2c3e50", height=40)
        tb.pack(fill=tk.X)
        tk.Label(tb, text="📋 経費精算 仕訳入力ツール", bg="#2c3e50", fg="white",
                 font=("Yu Gothic UI",12,"bold")).pack(side=tk.LEFT, padx=12, pady=6)
        tk.Button(tb, text="🔄 Excel再読込", command=self._load_data,
                  bg="#3498db", fg="white", relief=tk.FLAT, padx=8).pack(side=tk.RIGHT, padx=6, pady=5)
        tk.Button(tb, text="💾 CSV出力", command=self._export_csv,
                  bg="#27ae60", fg="white", relief=tk.FLAT, padx=8).pack(side=tk.RIGHT, padx=2, pady=5)
        main = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                              sashrelief=tk.RAISED, sashwidth=5, bg="#bdc3c7")
        main.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        left  = tk.Frame(main, bg="#f0f0f0"); main.add(left,  minsize=220, width=310)
        mid   = tk.Frame(main, bg="#f0f0f0"); main.add(mid,   minsize=280, width=380)
        right = tk.Frame(main, bg="#1a1a2e"); main.add(right, minsize=300, width=700)
        self._build_list_pane(left)
        self._build_form_pane(mid)
        self._build_viewer_pane(right)

    def _build_list_pane(self, parent):
        tk.Label(parent, text="■ 承認済みデータ一覧", bg="#f0f0f0",
                 font=("Yu Gothic UI",9,"bold"), anchor="w").pack(fill=tk.X, padx=6, pady=(6,2))
        self.summary_label = tk.Label(parent, text="読込中...", bg="#f0f0f0",
                                      font=("Yu Gothic UI",8), fg="#555", anchor="w")
        self.summary_label.pack(fill=tk.X, padx=6)
        frame = tk.Frame(parent, bg="#f0f0f0")
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        cols = [c[0] for c in LIST_COLS]
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for key, label, w in LIST_COLS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=w, minwidth=30, anchor="center")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.tag_configure("saved",   background="#d5f5e3")
        self.tree.tag_configure("unsaved", background="#fdfefe")
        self.tree.tag_configure("warning", background="#fef9e7")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_form_pane(self, parent):
        tk.Label(parent, text="■ 詳細・手入力フォーム", bg="#f0f0f0",
                 font=("Yu Gothic UI",9,"bold"), anchor="w").pack(fill=tk.X, padx=6, pady=(6,2))
        canvas = tk.Canvas(parent, bg="#f0f0f0", highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas, bg="#f0f0f0")
        win_id = canvas.create_window((0,0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        def _form_scroll(e):
            canvas.yview_scroll(-1*(e.delta//120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _form_scroll))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        inner.bind("<Enter>",  lambda e: canvas.bind_all("<MouseWheel>", _form_scroll))
        inner.bind("<Leave>",  lambda e: canvas.unbind_all("<MouseWheel>"))

        # 元データ参照
        sec1 = tk.LabelFrame(inner, text=" 元データ（参照） ", bg="#f0f0f0",
                              font=("Yu Gothic UI",8,"bold"), fg="#2980b9")
        sec1.pack(fill=tk.X, padx=6, pady=(4,2))
        self.ref_vars = {}
        for key, label in REF_FIELDS:
            rf = tk.Frame(sec1, bg="#f0f0f0"); rf.pack(fill=tk.X, pady=1)
            tk.Label(rf, text=label+":", width=10, anchor="e", bg="#f0f0f0",
                     font=("Yu Gothic UI",8), fg="#555").pack(side=tk.LEFT)
            var = tk.StringVar(); self.ref_vars[key] = var
            tk.Label(rf, textvariable=var, anchor="w", bg="#eaf2fb", relief=tk.FLAT,
                     font=("Yu Gothic UI",8), fg="#1a252f",
                     width=22).pack(side=tk.LEFT, padx=(2,4))

        # 手入力
        sec2 = tk.LabelFrame(inner, text=" 手入力エリア（経理担当者記入） ", bg="#f0f0f0",
                              font=("Yu Gothic UI",8,"bold"), fg="#e74c3c")
        sec2.pack(fill=tk.X, padx=6, pady=(6,2))

        # 補助科目コード（コンボ）
        rf = tk.Frame(sec2, bg="#f0f0f0"); rf.pack(fill=tk.X, pady=2)
        tk.Label(rf, text="補助科目ｺｰﾄﾞ:", width=12, anchor="e", bg="#f0f0f0",
                 font=("Yu Gothic UI",8)).pack(side=tk.LEFT)
        self.sub_cd_var = tk.StringVar()
        self.sub_combo = ttk.Combobox(rf, textvariable=self.sub_cd_var,
                                      width=26, font=("Yu Gothic UI",9))
        self.sub_combo.pack(side=tk.LEFT, padx=(2,4))
        self.sub_combo.bind("<<ComboboxSelected>>", self._on_sub_cd_select)

        # 補助科目名（自動入力）
        rf = tk.Frame(sec2, bg="#f0f0f0"); rf.pack(fill=tk.X, pady=2)
        tk.Label(rf, text="補助科目名:", width=12, anchor="e", bg="#f0f0f0",
                 font=("Yu Gothic UI",8)).pack(side=tk.LEFT)
        self.sub_name_var = tk.StringVar()
        self.sub_name_entry = tk.Entry(rf, textvariable=self.sub_name_var,
                                       width=28, font=("Yu Gothic UI",9),
                                       bg="white", relief=tk.SOLID, bd=1)
        self.sub_name_entry.pack(side=tk.LEFT, padx=(2,4))

        # その他手入力フィールド
        self.manual_vars = {"sub_cd": self.sub_cd_var, "sub_name": self.sub_name_var}
        self.manual_entries = {}
        for key, label in MANUAL_FIELDS:
            if key in ("sub_cd", "sub_name"):
                continue
            rf = tk.Frame(sec2, bg="#f0f0f0"); rf.pack(fill=tk.X, pady=2)
            tk.Label(rf, text=label+":", width=12, anchor="e", bg="#f0f0f0",
                     font=("Yu Gothic UI",8)).pack(side=tk.LEFT)
            var = tk.StringVar(); self.manual_vars[key] = var
            if key == "tax_kbn":
                # 税区分：略称コンボ
                self.tax_kbn_combo = ttk.Combobox(
                    rf, textvariable=var, width=14,
                    font=("Yu Gothic UI",9), state="readonly",
                    values=self.zeikunn_labels)
                self.tax_kbn_combo.pack(side=tk.LEFT, padx=(2,4))
                self.tax_kbn_combo.bind("<<ComboboxSelected>>", self._on_tax_kbn_select)
            elif key == "tax_rate":
                # 税率：固定3択コンボ
                self.tax_rate_combo = ttk.Combobox(
                    rf, textvariable=var, width=10,
                    font=("Yu Gothic UI",9), state="readonly",
                    values=TAX_RATE_OPTIONS)
                self.tax_rate_combo.pack(side=tk.LEFT, padx=(2,4))
            else:
                ent = tk.Entry(rf, textvariable=var, width=18,
                               font=("Yu Gothic UI",9), bg="white", relief=tk.SOLID, bd=1)
                ent.pack(side=tk.LEFT, padx=(2,4))
                self.manual_entries[key] = ent

        # ナビゲーション
        nav = tk.Frame(inner, bg="#f0f0f0"); nav.pack(fill=tk.X, padx=6, pady=8)
        tk.Button(nav, text="◀ 前へ", command=self._go_prev,
                  bg="#95a5a6", fg="white", relief=tk.FLAT,
                  font=("Yu Gothic UI",9), padx=6).pack(side=tk.LEFT)
        tk.Button(nav, text="保存して次へ ▶", command=self._save_and_next,
                  bg="#e67e22", fg="white", relief=tk.FLAT,
                  font=("Yu Gothic UI",9,"bold"), padx=8).pack(side=tk.RIGHT)
        tk.Button(nav, text="✔ 保存", command=self._save_current,
                  bg="#27ae60", fg="white", relief=tk.FLAT,
                  font=("Yu Gothic UI",9), padx=6).pack(side=tk.RIGHT, padx=4)

    def _on_sub_cd_select(self, event=None):
        selected = self.sub_cd_var.get()
        mapping  = getattr(self, "_sub_mapping", {})
        if selected in mapping:
            cd, nm = mapping[selected]
            self.sub_cd_var.set(cd)
            self.sub_name_var.set(nm)

    def _on_tax_kbn_select(self, event=None):
        abr = self.manual_vars["tax_kbn"].get()
        cd  = self.zeikunn_mapping.get(abr, abr)
        self.manual_vars["tax_kbn"].set(cd)

    def _build_viewer_pane(self, parent):
        top = tk.Frame(parent, bg="#16213e"); top.pack(fill=tk.X)
        tk.Label(top, text="証憑:", bg="#16213e", fg="#aaa",
                 font=("Yu Gothic UI",8)).pack(side=tk.LEFT, padx=6)
        self.voucher_var = tk.StringVar()
        self.voucher_combo = ttk.Combobox(top, textvariable=self.voucher_var,
                                          width=28, state="readonly", font=("Yu Gothic UI",8))
        self.voucher_combo.pack(side=tk.LEFT, padx=4, pady=4)
        self.voucher_combo.bind("<<ComboboxSelected>>", self._on_voucher_select)
        tk.Button(top, text="📂 追加", command=self._add_voucher,
                  bg="#0f3460", fg="#eee", relief=tk.FLAT,
                  font=("Yu Gothic UI",8), padx=4).pack(side=tk.LEFT, padx=2)

        pf = tk.Frame(parent, bg="#16213e"); pf.pack(fill=tk.X)
        tk.Button(pf, text="◀", command=self._prev_page,
                  bg="#0f3460", fg="white", relief=tk.FLAT, width=3).pack(side=tk.LEFT, padx=6, pady=2)
        self.page_label = tk.Label(pf, text="", bg="#16213e", fg="#ccc",
                                   font=("Yu Gothic UI",8))
        self.page_label.pack(side=tk.LEFT)
        tk.Button(pf, text="▶", command=self._next_page,
                  bg="#0f3460", fg="white", relief=tk.FLAT, width=3).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(pf, text="＋", command=lambda: self._zoom(1.2),
                  bg="#0f3460", fg="white", relief=tk.FLAT, width=2).pack(side=tk.RIGHT, padx=2)
        tk.Button(pf, text="－", command=lambda: self._zoom(0.8),
                  bg="#0f3460", fg="white", relief=tk.FLAT, width=2).pack(side=tk.RIGHT, padx=2)
        tk.Label(pf, text="ズーム:", bg="#16213e", fg="#aaa",
                 font=("Yu Gothic UI",8)).pack(side=tk.RIGHT, padx=4)

        cvf = tk.Frame(parent, bg="#1a1a2e"); cvf.pack(fill=tk.BOTH, expand=True)
        self.viewer_canvas = tk.Canvas(cvf, bg="#1a1a2e",
                                       highlightthickness=0, cursor="crosshair")
        hbar = ttk.Scrollbar(cvf, orient=tk.HORIZONTAL, command=self.viewer_canvas.xview)
        vbar = ttk.Scrollbar(cvf, orient=tk.VERTICAL,   command=self.viewer_canvas.yview)
        self.viewer_canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        hbar.pack(side=tk.BOTTOM, fill=tk.X)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.viewer_canvas.pack(fill=tk.BOTH, expand=True)
        def _viewer_scroll(e):
            self.viewer_canvas.yview_scroll(-1*(e.delta//120), "units")
        self.viewer_canvas.bind("<Enter>",
            lambda e: self.viewer_canvas.bind_all("<MouseWheel>", _viewer_scroll))
        self.viewer_canvas.bind("<Leave>",
            lambda e: self.viewer_canvas.unbind_all("<MouseWheel>"))
        self.viewer_canvas.create_text(300, 200,
            text="← 証憑ファイルを選択してください",
            fill="#555", font=("Yu Gothic UI",11))

    # ─── データ読込 ───
    def _load_data(self):
        try:
            self.df = load_fns_data(EXCEL_PATH)
        except Exception as e:
            messagebox.showerror("読込エラー", str(e)); return
        self._refresh_tree()
        if len(self.df) > 0:
            self.tree.selection_set(self.tree.get_children()[0])
            self._on_select(None)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        saved = sum(1 for v in self.manual_data.values() if any(v.values()))
        self.summary_label.config(
            text=f"全{len(self.df)}件  保存済:{saved}件  未処理:{len(self.df)-saved}件")
        for i, row in self.df.iterrows():
            did = str(row.get("document_detail_id", i))
            acd = build_account_cd(str(row.get("account_cd","")), str(row.get("bumon_cd","")))
            if acd.startswith("??"):
                tag, status = "warning", "⚠ 要確認"
            elif self.manual_data.get(did):
                tag, status = "saved",   "✔ 済"
            else:
                tag, status = "unsaved", "未入力"
            vals = [
                row.get("_row_no", i+1),
                str(row.get("date",""))[:10],
                str(row.get("applicant_name",""))[:8],
                str(row.get("account_name",""))[:8],
                str(row.get("amount","")),
                str(row.get("purpose",""))[:14],
                status,
            ]
            self.tree.insert("", tk.END, iid=str(i), values=vals, tags=(tag,))

    # ─── 一覧選択 → フォーム展開 ───
    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        self.current_idx = idx
        row = self.df.iloc[idx]
        did     = str(row.get("document_detail_id", idx))
        raw_acd = str(row.get("account_cd","")).strip()

        for key, _ in REF_FIELDS:
            val = str(row.get(key,"")) if pd.notna(row.get(key,"")) else ""
            if key == "date":
                val = val[:10]
            elif key == "account_cd":
                val = build_account_cd(val, str(row.get("bumon_cd","")))
            self.ref_vars[key].set(val)

        labels, mapping = self._get_hojo_options(raw_acd)
        self._sub_mapping = mapping
        saved = self.manual_data.get(did, {})

        if labels:
            self.sub_combo.configure(state="readonly", values=labels)
            restored = ""
            for lbl, (cd, nm) in mapping.items():
                if cd == saved.get("sub_cd",""):
                    restored = lbl; break
            self.sub_cd_var.set(restored)
            self.sub_name_var.set(saved.get("sub_name",""))
            self.sub_name_entry.configure(state="readonly", bg="#eaf2fb")
        else:
            self.sub_combo.configure(state="disabled", values=[])
            self.sub_cd_var.set("")
            self.sub_name_var.set("")
            self.sub_name_entry.configure(state="disabled", bg="#e8e8e8")

        # 税区分：保存済みコード → 略称に変換して表示
        saved_tax_cd = saved.get("tax_kbn","")
        abr_display  = next((abr for abr, cd in self.zeikunn_mapping.items()
                             if cd == saved_tax_cd), saved_tax_cd)
        self.manual_vars["tax_kbn"].set(abr_display)

        # 税率：保存済み値をそのまま復元
        self.manual_vars["tax_rate"].set(saved.get("tax_rate",""))

        # その他手入力
        for key, _ in MANUAL_FIELDS:
            if key in ("sub_cd", "sub_name", "tax_kbn", "tax_rate"): continue
            self.manual_vars[key].set(saved.get(key,""))

    # ─── 保存・ナビ ───
    def _save_current(self):
        if self.current_idx < 0 or len(self.df) == 0: return
        row     = self.df.iloc[self.current_idx]
        did     = str(row.get("document_detail_id", self.current_idx))
        raw_acd = str(row.get("account_cd","")).strip()
        labels, mapping = self._get_hojo_options(raw_acd)

        sub_label = self.sub_cd_var.get()
        if sub_label in mapping:
            sub_cd, sub_name = mapping[sub_label]
        else:
            sub_cd   = sub_label
            sub_name = self.sub_name_var.get()

        # 税区分：表示中の略称 → コードに変換
        tax_val = self.manual_vars["tax_kbn"].get()
        tax_cd  = self.zeikunn_mapping.get(tax_val, tax_val)

        self.manual_data[did] = {
            "sub_cd":   sub_cd,
            "sub_name": sub_name,
            "tax_kbn":  tax_cd,
            "tax_rate": self.manual_vars["tax_rate"].get(),
            **{k: self.manual_vars[k].get()
               for k, _ in MANUAL_FIELDS
               if k not in ("sub_cd","sub_name","tax_kbn","tax_rate")},
        }
        self._refresh_tree()
        self.tree.selection_set(str(self.current_idx))

    def _save_and_next(self):
        self._save_current()
        nxt = self.current_idx + 1
        if nxt < len(self.df):
            self.tree.selection_set(str(nxt)); self._on_select(None)
        else:
            messagebox.showinfo("完了", "最後のレコードです。CSV出力してください。")

    def _go_prev(self):
        if self.current_idx > 0:
            self.tree.selection_set(str(self.current_idx - 1)); self._on_select(None)

    # ─── 証憑ビューア ───
    def _load_vouchers(self):
        exts = (".pdf",".jpg",".jpeg",".png",".bmp",".gif")
        files = [f for f in sorted(os.listdir(VOUCHER_DIR))
                 if f.lower().endswith(exts)] if os.path.isdir(VOUCHER_DIR) else []
        self.voucher_files = files
        self.voucher_combo["values"] = files
        if files:
            self.voucher_combo.current(0); self._render_voucher()

    def _add_voucher(self):
        path = filedialog.askopenfilename(
            title="証憑ファイルを選択",
            filetypes=[("対応ファイル","*.pdf *.jpg *.jpeg *.png *.bmp"),("All","*.*")])
        if not path: return
        import shutil
        fname = os.path.basename(path)
        dest  = os.path.join(VOUCHER_DIR, fname)
        if not os.path.exists(dest): shutil.copy(path, dest)
        self._load_vouchers()
        if fname in self.voucher_files:
            self.voucher_combo.current(self.voucher_files.index(fname))
            self._render_voucher()

    def _on_voucher_select(self, event=None):
        self.pdf_page_no = 0; self.zoom_level = 1.0; self.pdf_doc = None
        self._render_voucher()

    def _render_voucher(self):
        fname = self.voucher_var.get()
        if not fname: return
        fpath = os.path.join(VOUCHER_DIR, fname)
        ext   = os.path.splitext(fname)[1].lower()
        try:
            if ext == ".pdf": self._render_pdf(fpath)
            else:             self._render_image(fpath)
        except Exception as e:
            self.viewer_canvas.delete("all")
            self.viewer_canvas.create_text(300, 200, text=f"表示エラー:\n{e}",
                                           fill="#e74c3c", font=("Yu Gothic UI",10))

    def _render_pdf(self, path):
        if self.pdf_doc is None or self.pdf_doc.name != path:
            self.pdf_doc = fitz.open(path); self.pdf_page_no = 0
        total = len(self.pdf_doc)
        self.pdf_page_no = max(0, min(self.pdf_page_no, total-1))
        self.page_label.config(text=f"  {self.pdf_page_no+1} / {total}  ")
        page = self.pdf_doc[self.pdf_page_no]
        mat  = fitz.Matrix(self.zoom_level * 1.5, self.zoom_level * 1.5)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        self._display_image(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))

    def _render_image(self, path):
        self.pdf_doc = None
        self.page_label.config(text="  画像  ")
        img = Image.open(path)
        img = img.resize((int(img.width*self.zoom_level),
                          int(img.height*self.zoom_level)), Image.LANCZOS)
        self._display_image(img)

    def _display_image(self, img):
        self.photo_img = ImageTk.PhotoImage(img)
        self.viewer_canvas.delete("all")
        self.viewer_canvas.create_image(0, 0, anchor="nw", image=self.photo_img)
        self.viewer_canvas.configure(scrollregion=(0, 0, img.width, img.height))

    def _prev_page(self):
        if self.pdf_doc and self.pdf_page_no > 0:
            self.pdf_page_no -= 1; self._render_voucher()

    def _next_page(self):
        if self.pdf_doc and self.pdf_page_no < len(self.pdf_doc) - 1:
            self.pdf_page_no += 1; self._render_voucher()

    def _zoom(self, factor):
        self.zoom_level = max(0.3, min(4.0, self.zoom_level * factor))
        self._render_voucher()

    # ─── CSV出力 ───
    def _export_csv(self):
        if len(self.df) == 0:
            messagebox.showwarning("警告", "データがありません"); return
        warns = []
        for i, row in self.df.iterrows():
            acd = build_account_cd(str(row.get("account_cd","")), str(row.get("bumon_cd","")))
            if acd.startswith("??"):
                warns.append(f"  行{row.get('_row_no','?')}: 部門{row.get('bumon_cd','')} 元コード:{row.get('account_cd','')}")
        if warns:
            msg = ("以下の行で部門コードが未登録のため科目コードを正確に変換できません:\n"
                   + "\n".join(warns) + "\n\nそのままCSVを出力しますか？")
            if not messagebox.askyesno("⚠ 警告", msg): return
        save_path = filedialog.asksaveasfilename(
            title="仕訳CSVの保存先", defaultextension=".csv",
            initialfile="仕訳取込.csv",
            filetypes=[("CSV","*.csv"),("All","*.*")])
        if not save_path: return
        rows = []
        for i, row in self.df.iterrows():
            did = str(row.get("document_detail_id", i))
            m   = self.manual_data.get(did, {})
            def v(key, r=row):
                val = r.get(key, "")
                return "" if pd.isna(val) or str(val)=="nan" else str(val)
            date_val = v("date")[:10] if len(v("date")) >= 10 else v("date")
            acd5     = build_account_cd(v("account_cd"), v("bumon_cd"))
            rows.append({
                "伝票区切":      "*",
                "伝票日付":      date_val,
                "部門ｺｰﾄﾞ":     v("bumon_cd"),
                "部門名":        v("bumon_name"),
                "科目ｺｰﾄﾞ":     acd5,
                "科目名":        v("account_name"),
                "補助科目ｺｰﾄﾞ": m.get("sub_cd",   ""),
                "補助科目名":    m.get("sub_name", ""),
                "税抜金額":      v("amount"),
                "税金額":        m.get("tax_amt",  ""),
                "税区分":        m.get("tax_kbn",  ""),
                "税率":          m.get("tax_rate", ""),
                "外貨ｺｰﾄﾞ":     v("tsuka_cd"),
                "換算ﾚｰﾄ":       m.get("fx_rate",  ""),
                "外貨金額":      v("amount"),
                "外貨税額":      m.get("fx_tax",   ""),
                "摘要（品名）":  v("purpose"),
            })
        pd.DataFrame(rows).to_csv(save_path, index=False, encoding="utf-8-sig")
        messagebox.showinfo("完了", f"CSVを出力しました:\n{save_path}")

if __name__ == "__main__":
    app = ExpenseApp()
    app.mainloop()
