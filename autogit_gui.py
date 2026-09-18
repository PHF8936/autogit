import os
import time
import ssl
import certifi
import urllib3

# ========== 彻底禁用 SSL 验证（打包 exe 后也能用） ==========
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import json
import threading
import base64
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from github import Github, InputGitTreeElement, Auth

# ========== 全局主题 ==========
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLOR_BG = "#1e1e2e"
COLOR_PANEL = "#282838"
COLOR_PANEL_2 = "#313145"
COLOR_ACCENT = "#4a9eff"
COLOR_ACCENT_HOVER = "#3a8eef"
COLOR_SUCCESS = "#4ade80"
COLOR_DANGER = "#f87171"
COLOR_TEXT = "#e0e0e0"
COLOR_TEXT_DIM = "#8a8a9a"

CONFIG_FILE = os.path.join(
    os.path.expanduser("~"), ".github_uploader_config.json"
)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def make_github(token):
    return Github(
        auth=Auth.Token(token),
        timeout=60,
        retry=5,
        pool_size=10,
    )


class GitHubUploaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GitHub 文件上传器")
        self.geometry("1040x720")
        self.configure(fg_color=COLOR_BG)
        self.config_data = load_config()
        self.github = None
        self.repo = None
        self._folder_root = None

        self._setup_tree_style()
        self._build_ui()
        self._restore_session()

    # ---------- Treeview 深色样式 ----------
    def _setup_tree_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.Treeview",
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            fieldbackground=COLOR_PANEL,
            borderwidth=0,
            rowheight=28,
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", COLOR_ACCENT)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=COLOR_PANEL_2,
            foreground=COLOR_TEXT,
            relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Dark.Treeview.Heading",
            background=[("active", COLOR_PANEL_2)],
        )

    # ---------- 界面 ----------
    def _build_ui(self):
        # 顶部状态栏
        top = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=12, height=56)
        top.pack(fill="x", padx=16, pady=(16, 8))
        top.pack_propagate(False)

        self.status_dot = ctk.CTkLabel(
            top, text="●", text_color=COLOR_DANGER, font=("", 18)
        )
        self.status_dot.pack(side="left", padx=(16, 4))
        self.status_label = ctk.CTkLabel(
            top, text="未登录", text_color=COLOR_TEXT_DIM,
            font=("Microsoft YaHei UI", 12)
        )
        self.status_label.pack(side="left")

        ctk.CTkButton(
            top, text="登录 GitHub",
            command=self.open_login_dialog,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8, width=110, height=32,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="right", padx=16)

        # 中部左右分栏
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=16, pady=8)
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_columnconfigure(1, weight=1)
        mid.grid_rowconfigure(0, weight=1)

        # ---------- 左侧：本地文件 ----------
        left = ctk.CTkFrame(mid, fg_color=COLOR_PANEL, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        left_header = ctk.CTkFrame(left, fg_color="transparent")
        left_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            left_header, text="📁  本地文件",
            font=("Microsoft YaHei UI", 13, "bold"), text_color=COLOR_TEXT
        ).pack(side="left")
        ctk.CTkButton(
            left_header, text="选择文件夹",
            command=self.select_local_folder,
            fg_color=COLOR_PANEL_2, hover_color="#3a3a52",
            corner_radius=8, width=90, height=28,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="right")

        self.local_tree = ttk.Treeview(
            left, show="tree", columns=("selected",),
            style="Dark.Treeview"
        )
        self.local_tree.column("#0", width=260)
        self.local_tree.column("selected", width=50, anchor="center")
        self.local_tree.heading("#0", text="文件")
        self.local_tree.heading("selected", text="✓")
        self.local_tree.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.local_tree.bind("<Button-1>", self.on_local_click)

        # ---------- 右侧：远程仓库 ----------
        right = ctk.CTkFrame(mid, fg_color=COLOR_PANEL, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(1, weight=0)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        right_header = ctk.CTkFrame(right, fg_color="transparent")
        right_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            right_header, text="☁  远程仓库",
            font=("Microsoft YaHei UI", 13, "bold"), text_color=COLOR_TEXT
        ).pack(side="left")

        repo_frame = ctk.CTkFrame(right, fg_color="transparent")
        repo_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.repo_combo = ctk.CTkComboBox(
            repo_frame, values=[], command=self.on_repo_selected,
            fg_color=COLOR_PANEL_2, border_color=COLOR_PANEL_2,
            button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
            dropdown_fg_color=COLOR_PANEL_2,
            corner_radius=8, height=32,
            font=("Microsoft YaHei UI", 10),
        )
        self.repo_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            repo_frame, text="刷新", width=60, height=32,
            command=self.load_repos,
            fg_color=COLOR_PANEL_2, hover_color="#3a3a52",
            corner_radius=8, font=("Microsoft YaHei UI", 10),
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            repo_frame, text="新建", width=60, height=32,
            command=self.open_create_repo_dialog,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8, font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="right")

        # ===== 新增：删除仓库按钮 =====
        ctk.CTkButton(
            repo_frame, text="删除", width=60, height=32,
            command=self.open_delete_repo_dialog,
            fg_color="#b91c1c", hover_color="#991b1b",
            corner_radius=8, font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="right", padx=(0, 6))

        # ===== 新增：分支管理按钮 =====
        ctk.CTkButton(
            repo_frame, text="分支", width=60, height=32,
            command=self.open_branch_dialog,
            fg_color=COLOR_PANEL_2, hover_color="#3a3a52",
            corner_radius=8, font=("Microsoft YaHei UI", 10),
        ).pack(side="right", padx=(0, 6))

        self.remote_tree = ttk.Treeview(
            right, show="tree", columns=("path",),
            style="Dark.Treeview"
        )
        self.remote_tree.column("#0", width=260)
        self.remote_tree.column("path", width=0, stretch=False)
        self.remote_tree.heading("#0", text="仓库目录")
        self.remote_tree.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # ---------- 底部操作区 ----------
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 8))

        self.upload_btn = ctk.CTkButton(
            bottom, text="⬆  上传选中文件",
            command=self.start_upload, state="disabled",
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=10, height=40, width=180,
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.upload_btn.pack(side="left")

        self.progress = ctk.CTkProgressBar(
            bottom, width=300, height=10,
            progress_color=COLOR_ACCENT, fg_color=COLOR_PANEL_2,
        )
        self.progress.pack(side="left", padx=16)
        self.progress.set(0)

        # ---------- 日志区 ----------
        self.log_text = ctk.CTkTextbox(
            self, height=130,
            fg_color="#15151f", text_color=COLOR_TEXT_DIM,
            corner_radius=12, border_width=0,
            font=("Consolas", 10),
        )
        self.log_text.pack(fill="x", padx=16, pady=(0, 16))

    # ---------- 登录 ----------
    def open_login_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("登录 GitHub")
        dialog.geometry("440x280")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="登录 GitHub",
            font=("Microsoft YaHei UI", 15, "bold"), text_color=COLOR_TEXT
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            dialog, text="请输入 Personal Access Token",
            text_color=COLOR_TEXT_DIM, font=("Microsoft YaHei UI", 10)
        ).pack()

        token_entry = ctk.CTkEntry(
            dialog, width=360, show="*",
            fg_color=COLOR_PANEL_2, border_color=COLOR_PANEL_2,
            corner_radius=8, height=36,
        )
        token_entry.pack(pady=14)
        ctk.CTkLabel(
            dialog, text="需勾选 repo 权限（Classic Token）",
            text_color=COLOR_TEXT_DIM, font=("Microsoft YaHei UI", 9)
        ).pack()

        def do_login():
            token = token_entry.get().strip()
            if not token:
                messagebox.showwarning("提示", "请输入 Token")
                return
            try:
                gh = make_github(token)
                username = gh.get_user().login
                self.config_data["github_token"] = token
                self.config_data["github_username"] = username
                save_config(self.config_data)
                self.github = gh
                self.status_dot.configure(text_color=COLOR_SUCCESS)
                self.status_label.configure(
                    text=f"已登录: {username}", text_color=COLOR_TEXT
                )
                self.upload_btn.configure(state="normal")
                dialog.destroy()
                self.load_repos()
                self.log(f"✓ 登录成功: {username}")
            except Exception as e:
                messagebox.showerror("登录失败", str(e))

        ctk.CTkButton(
            dialog, text="登录", command=do_login,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8, height=36, width=200,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=10)

    def _restore_session(self):
        token = self.config_data.get("github_token")
        if not token:
            return
        try:
            self.github = make_github(token)
            user = self.github.get_user()
            self.status_dot.configure(text_color=COLOR_SUCCESS)
            self.status_label.configure(
                text=f"已登录: {user.login}", text_color=COLOR_TEXT
            )
            self.upload_btn.configure(state="normal")
            self.load_repos()
        except Exception:
            pass

    # ---------- 新建仓库 ----------
    def open_create_repo_dialog(self):
        if not self.github:
            messagebox.showwarning("提示", "请先登录")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("新建仓库")
        dialog.geometry("440x360")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="新建仓库",
            font=("Microsoft YaHei UI", 15, "bold"), text_color=COLOR_TEXT
        ).pack(pady=(24, 12))

        ctk.CTkLabel(
            dialog, text="仓库名称", text_color=COLOR_TEXT_DIM,
            font=("Microsoft YaHei UI", 10)
        ).pack(anchor="w", padx=40)
        name_entry = ctk.CTkEntry(
            dialog, width=360, fg_color=COLOR_PANEL_2,
            border_color=COLOR_PANEL_2, corner_radius=8, height=36,
        )
        name_entry.pack(pady=(4, 12))

        ctk.CTkLabel(
            dialog, text="描述（可选）", text_color=COLOR_TEXT_DIM,
            font=("Microsoft YaHei UI", 10)
        ).pack(anchor="w", padx=40)
        desc_entry = ctk.CTkEntry(
            dialog, width=360, fg_color=COLOR_PANEL_2,
            border_color=COLOR_PANEL_2, corner_radius=8, height=36,
        )
        desc_entry.pack(pady=(4, 12))

        private_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            dialog, text="私有仓库", variable=private_var,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            font=("Microsoft YaHei UI", 10),
        ).pack(pady=6)

        def do_create():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("提示", "请输入仓库名")
                return
            try:
                user = self.github.get_user()
                user.create_repo(
                    name=name,
                    description=desc_entry.get().strip(),
                    private=private_var.get(),
                    auto_init=True,
                )
                self.log(f"✓ 仓库创建成功: {name}")
                dialog.destroy()
                self.load_repos()
            except Exception as e:
                messagebox.showerror("创建失败", str(e))

        ctk.CTkButton(
            dialog, text="创建", command=do_create,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8, height=36, width=200,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=16)

    # ---------- 本地文件 ----------
    def select_local_folder(self):
        folder = filedialog.askdirectory(title="选择要上传的文件夹")
        if folder:
            self._load_local_folder(folder)

    def _load_local_folder(self, folder):
        self.local_tree.delete(*self.local_tree.get_children())
        self._folder_root = folder
        root_node = self.local_tree.insert(
            "", "end", text=os.path.basename(folder), values=("☐",), open=True
        )
        self._populate_local_tree(root_node, folder)

    def _populate_local_tree(self, parent, path):
        try:
            for item in sorted(os.listdir(path)):
                if item.startswith("."):
                    continue
                full = os.path.join(path, item)
                node = self.local_tree.insert(
                    parent, "end", text=item, values=("☐",)
                )
                if os.path.isdir(full):
                    self._populate_local_tree(node, full)
        except PermissionError:
            pass

    def on_local_click(self, event):
        item = self.local_tree.identify_row(event.y)
        if not item:
            return
        current = self.local_tree.set(item, "selected")
        self.local_tree.set(item, "selected", "☑" if current == "☐" else "☐")

    def _get_checked_files(self, node):
        result = []
        if self.local_tree.set(node, "selected") == "☑":
            path_parts = []
            n = node
            while n:
                path_parts.insert(0, self.local_tree.item(n, "text"))
                n = self.local_tree.parent(n)
            full_path = os.path.join(self._folder_root, *path_parts[1:])
            if os.path.isfile(full_path):
                result.append(full_path)
        for child in self.local_tree.get_children(node):
            result.extend(self._get_checked_files(child))
        return result

    # ---------- 远程仓库 ----------
    def load_repos(self):
        if not self.github:
            return
        try:
            repos = [r.name for r in self.github.get_user().get_repos()]
            self.repo_combo.configure(values=repos)
            if repos:
                self.repo_combo.set(repos[0])
                self.on_repo_selected(repos[0])
        except Exception as e:
            self.log(f"✗ 获取仓库失败: {e}")

    def on_repo_selected(self, repo_name):
        if not repo_name or not self.github:
            return
        try:
            self.repo = self.github.get_user().get_repo(repo_name)
            self._load_remote_tree()
        except Exception as e:
            self.log(f"✗ 加载仓库失败: {e}")

    def _load_remote_tree(self):
        self.remote_tree.delete(*self.remote_tree.get_children())
        root = self.remote_tree.insert(
            "", "end", text="/ (仓库根目录)", values=("",), open=True
        )
        self._populate_remote_tree(root, "")
        self.remote_tree.selection_set(root)

    def _populate_remote_tree(self, parent, path):
        try:
            contents = self.repo.get_contents(path)
            for item in contents:
                if item.type == "dir":
                    node = self.remote_tree.insert(
                        parent, "end", text=item.name, values=(item.path,)
                    )
                    self._populate_remote_tree(node, item.path)
                else:
                    self.remote_tree.insert(
                        parent, "end", text=item.name, values=(item.path,)
                    )
        except Exception:
            pass

    def _get_selected_remote_folder(self):
        sel = self.remote_tree.selection()
        if sel:
            return self.remote_tree.set(sel[0], "path")
        return ""

    # ---------- 上传 ----------
    def start_upload(self):
        if not self._folder_root:
            messagebox.showwarning("提示", "请先选择本地文件夹")
            return

        children = self.local_tree.get_children()
        selected_files = self._get_checked_files(children[0]) if children else []

        if not selected_files:
            for dirpath, _, filenames in os.walk(self._folder_root):
                for fn in filenames:
                    if not fn.startswith("."):
                        selected_files.append(os.path.join(dirpath, fn))

        if not selected_files:
            messagebox.showwarning("提示", "没有可上传的文件")
            return

        remote_folder = self._get_selected_remote_folder()
        self.upload_btn.configure(state="disabled", text="上传中...")
        self.progress.set(0)
        threading.Thread(
            target=self._do_upload,
            args=(self._folder_root, selected_files, remote_folder),
            daemon=True,
        ).start()

    def _do_upload(self, local_root, files, remote_folder):
        try:
            token = self.config_data.get("github_token")
            gh = make_github(token)
            repo = gh.get_user().get_repo(self.repo_combo.get())

            branch = repo.default_branch
            self.log(f"  目标仓库: {repo.full_name}, 分支: {branch}")

            # ===== 关键修复：先拿 commit 对象，再取 .tree.sha =====
            try:
                ref = repo.get_git_ref(f"heads/{branch}")
                current_commit_sha = ref.object.sha
                current_commit_obj = repo.get_git_commit(current_commit_sha)
                current_tree_sha = current_commit_obj.tree.sha
                self.log(f"  当前 HEAD: {current_commit_sha[:8]}")
                self.log(f"  当前 tree: {current_tree_sha[:8]}")
            except Exception as e:
                self.log(f"  分支 {branch} 不存在，将创建初始提交 ({e})")
                current_commit_sha = None
                current_tree_sha = None
            # =====================================================

            # ===== 分批参数 =====
            BATCH_SIZE = 20
            BATCH_DELAY = 0.5
            # ====================

            total = len(files)
            done = 0

            for i in range(0, total, BATCH_SIZE):
                batch = files[i:i + BATCH_SIZE]
                elements = []

                for local_path in batch:
                    rel_path = os.path.relpath(local_path, local_root).replace("\\", "/")
                    remote_path = (
                        f"{remote_folder}/{rel_path}" if remote_folder else rel_path
                    )
                    remote_path = remote_path.lstrip("/")

                    with open(local_path, "rb") as f:
                        content = f.read()

                    ext = os.path.splitext(local_path)[1].lower()
                    binary_exts = (
                        ".png", ".jpg", ".jpeg", ".gif", ".webp",
                        ".ico", ".pdf", ".zip", ".exe", ".dll",
                    )
                    if ext in binary_exts:
                        data = base64.b64encode(content).decode("utf-8")
                    else:
                        try:
                            data = content.decode("utf-8")
                        except UnicodeDecodeError:
                            data = base64.b64encode(content).decode("utf-8")

                    elements.append(
                        InputGitTreeElement(remote_path, "100644", "blob", data)
                    )

                self.log(f"  创建第 {i // BATCH_SIZE + 1} 批 tree ({len(batch)} 文件)...")
                # ===== 修复点：base_tree 必须是 GitTree 对象，不能是 str =====
                if current_tree_sha:
                    base_tree = repo.get_git_tree(current_tree_sha)
                    new_tree = repo.create_git_tree(elements, base_tree)
                else:
                    new_tree = repo.create_git_tree(elements)
                # ============================================================

                self.log(f"  创建 commit...")
                parent = repo.get_git_commit(current_commit_sha) if current_commit_sha else None
                commit = repo.create_git_commit(
                    f"upload batch {i // BATCH_SIZE + 1} ({len(batch)} files)",
                    new_tree,
                    [parent] if parent else [],
                )

                current_commit_sha = commit.sha
                current_tree_sha = new_tree.sha
                done += len(batch)

                self.log(f"  已上传 {done}/{total} 个文件 (commit {commit.sha[:8]})")
                self.progress.set(done / total)

                if i + BATCH_SIZE < total:
                    time.sleep(BATCH_DELAY)

            self.log(f"  更新分支 {branch}...")
            ref = repo.get_git_ref(f"heads/{branch}")
            ref.edit(current_commit_sha)

            self.log(f"✓ 上传成功: {total} 个文件 → {remote_folder or '/'}")
            self.log(f"  最终提交 SHA: {current_commit_sha[:8]}")
        except Exception as e:
            self.log(f"✗ 上传失败: {type(e).__name__}: {e}")
            self.log("--- 完整错误 ---")
            self.log(traceback.format_exc())
        finally:
            self.upload_btn.configure(state="normal", text="⬆  上传选中文件")

    # ============================================================
    # ========== 新增功能：删除仓库 / 查看&删除分支 ==========
    # ============================================================

    # ---------- 删除仓库 ----------
    def open_delete_repo_dialog(self):
        if not self.github:
            messagebox.showwarning("提示", "请先登录")
            return

        repo_name = self.repo_combo.get().strip()
        if not repo_name:
            messagebox.showwarning("提示", "请先在下拉框选择一个仓库")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("删除仓库")
        dialog.geometry("460x300")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="⚠  危险操作",
            font=("Microsoft YaHei UI", 15, "bold"), text_color=COLOR_DANGER
        ).pack(pady=(24, 6))

        ctk.CTkLabel(
            dialog,
            text=f"即将永久删除仓库：\n{repo_name}",
            text_color=COLOR_TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
            justify="center",
        ).pack(pady=(0, 10))

        ctk.CTkLabel(
            dialog,
            text="此操作不可恢复！请输入仓库名以确认：",
            text_color=COLOR_TEXT_DIM,
            font=("Microsoft YaHei UI", 10),
        ).pack()

        confirm_entry = ctk.CTkEntry(
            dialog, width=360, fg_color=COLOR_PANEL_2,
            border_color=COLOR_PANEL_2, corner_radius=8, height=36,
        )
        confirm_entry.pack(pady=10)

        def do_delete():
            typed = confirm_entry.get().strip()
            if typed != repo_name:
                messagebox.showwarning("提示", "输入的仓库名不匹配")
                return
            try:
                self.log(f"  正在删除仓库 {repo_name} ...")
                repo = self.github.get_user().get_repo(repo_name)
                repo.delete()
                self.log(f"✓ 仓库已删除: {repo_name}")
                dialog.destroy()
                # 刷新仓库列表
                self.repo = None
                self.remote_tree.delete(*self.remote_tree.get_children())
                self.load_repos()
            except Exception as e:
                messagebox.showerror("删除失败", str(e))
                self.log(f"✗ 删除仓库失败: {e}")

        ctk.CTkButton(
            dialog, text="确认删除", command=do_delete,
            fg_color="#b91c1c", hover_color="#991b1b",
            corner_radius=8, height=36, width=200,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=10)

    # ---------- 分支管理 ----------
    def open_branch_dialog(self):
        if not self.github:
            messagebox.showwarning("提示", "请先登录")
            return

        repo_name = self.repo_combo.get().strip()
        if not repo_name:
            messagebox.showwarning("提示", "请先在下拉框选择一个仓库")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"分支管理 - {repo_name}")
        dialog.geometry("560x460")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=f"分支管理：{repo_name}",
            font=("Microsoft YaHei UI", 14, "bold"), text_color=COLOR_TEXT
        ).pack(pady=(18, 8))

        # 顶部：默认分支显示
        top_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(0, 6))

        default_branch_label = ctk.CTkLabel(
            top_bar, text="默认分支: -",
            text_color=COLOR_TEXT_DIM, font=("Microsoft YaHei UI", 10)
        )
        default_branch_label.pack(side="left")

        # 分支列表（Treeview 深色）
        list_frame = ctk.CTkFrame(dialog, fg_color=COLOR_PANEL, corner_radius=10)
        list_frame.pack(fill="both", expand=True, padx=20, pady=6)

        branch_tree = ttk.Treeview(
            list_frame, show="tree", columns=("sha",),
            style="Dark.Treeview"
        )
        branch_tree.column("#0", width=260)
        branch_tree.column("sha", width=120, anchor="center")
        branch_tree.heading("#0", text="分支名")
        branch_tree.heading("sha", text="最新 SHA")
        branch_tree.pack(fill="both", expand=True, padx=8, pady=8)

        # 分支名与 SHA 的映射
        branch_sha_map = {}
        default_branch_holder = {"name": None}

        def refresh_branches():
            branch_tree.delete(*branch_tree.get_children())
            branch_sha_map.clear()
            try:
                repo = self.github.get_user().get_repo(repo_name)
                default_branch_holder["name"] = repo.default_branch
                default_branch_label.configure(
                    text=f"默认分支: {repo.default_branch}"
                )
                for br in repo.get_branches():
                    sha = br.commit.sha
                    branch_sha_map[br.name] = sha
                    tag = "  (默认)" if br.name == repo.default_branch else ""
                    branch_tree.insert(
                        "", "end",
                        text=f"{br.name}{tag}",
                        values=(sha[:8],),
                    )
                self.log(f"✓ 已加载 {len(branch_sha_map)} 个分支")
            except Exception as e:
                self.log(f"✗ 加载分支失败: {e}")
                messagebox.showerror("加载失败", str(e))

        def _selected_branch_name():
            sel = branch_tree.selection()
            if not sel:
                return None
            item = sel[0]
            display_name = branch_tree.item(item, "text")
            return display_name.replace("  (默认)", "").strip()

        def do_delete_branch():
            br_name = _selected_branch_name()
            if not br_name:
                messagebox.showwarning("提示", "请先选择一个分支")
                return
            if br_name == default_branch_holder["name"]:
                messagebox.showwarning("提示", "不能删除默认分支")
                return
            if not messagebox.askyesno(
                "确认删除",
                f"确定要删除分支 {br_name} 吗？\n此操作不可恢复。"
            ):
                return
            try:
                repo = self.github.get_user().get_repo(repo_name)
                ref = repo.get_git_ref(f"heads/{br_name}")
                ref.delete()
                self.log(f"✓ 分支已删除: {br_name}")
                refresh_branches()
            except Exception as e:
                messagebox.showerror("删除失败", str(e))
                self.log(f"✗ 删除分支失败: {e}")

        def do_switch_branch():
            """把选中分支设为默认分支"""
            br_name = _selected_branch_name()
            if not br_name:
                messagebox.showwarning("提示", "请先选择一个分支")
                return
            if br_name == default_branch_holder["name"]:
                messagebox.showinfo("提示", "该分支已经是默认分支")
                return
            try:
                repo = self.github.get_user().get_repo(repo_name)
                repo.edit(default_branch=br_name)
                self.log(f"✓ 默认分支已切换为: {br_name}")
                refresh_branches()
            except Exception as e:
                messagebox.showerror("切换失败", str(e))
                self.log(f"✗ 切换默认分支失败: {e}")

        # 底部按钮区
        btn_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=(6, 16))

        ctk.CTkButton(
            btn_bar, text="刷新", width=80, height=32,
            command=refresh_branches,
            fg_color=COLOR_PANEL_2, hover_color="#3a3a52",
            corner_radius=8, font=("Microsoft YaHei UI", 10),
        ).pack(side="left")

        ctk.CTkButton(
            btn_bar, text="设为默认", width=90, height=32,
            command=do_switch_branch,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8, font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_bar, text="删除分支", width=100, height=32,
            command=do_delete_branch,
            fg_color="#b91c1c", hover_color="#991b1b",
            corner_radius=8, font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="right")

        # 打开时自动加载
        refresh_branches()

    # ============================================================
    # ========== 新增功能结束 ==========
    # ============================================================

    def log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")


if __name__ == "__main__":
    app = GitHubUploaderApp()
    app.mainloop()