import time
import tkinter as tk
from tkinter import scrolledtext

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import ocr_tool
from aram_mayhem_helper.utils.data import champion_augment_data_dict, data
from aram_mayhem_helper.utils.log_config import setup_logging

current_champion_idd = None
suggest = None


# ====================== 第一步：定义日志输出函数（核心） ======================
def print_log(log_text, log_area):
    """
    向日志区域输出内容（带时间戳，自动滚动）
    :param log_text: 要打印的日志文本
    :param log_area: 日志显示区域对象
    """
    # 拼接时间戳，格式：[2026-02-20 15:30:00] 日志内容
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ", time.localtime())
    log_area.config(state=tk.NORMAL)  # 临时解锁日志区域，允许输入
    log_area.insert(tk.END, timestamp + log_text + "\n")  # 插入日志
    log_area.see(tk.END)  # 自动滚动到最新日志
    log_area.config(state=tk.DISABLED)  # 锁定日志区域，禁止手动编辑
    log_area.update()  # 实时刷新界面


# ====================== 第二步：定义业务函数（绑定按钮，带日志输出） ======================
def recognize_champion(log_area):
    """识别当前英雄"""
    print_log("开始执行「识别当前英雄」操作...", log_area)

    global suggest
    global current_champion_id

    try:
        champion_name = get_current_champion_name()
        current_champion_id = data.get_champion_id_by_name(champion_name)
        champion_augment_data = champion_augment_data_dict[current_champion_id]
        suggest = Suggest(champion_augment_data)
        print_log(f"当前英雄：{champion_name}", log_area)
    except Exception as e:
        print_log(f"「识别当前英雄」操作出错：{str(e)}", log_area)


def recognize_augment(log_area):
    """识别符文和展示结果"""
    print_log("开始执行「识别符文」操作...", log_area)
    try:
        # 模拟你的数据导出逻辑
        augments = ocr_tool.get_augments()
        augments_info = suggest.suggest(augments)
        for augment_info in augments_info:
            print_log(str(augment_info), log_area)
    except Exception as e:
        print_log(f"「识别符文」操作出错：{str(e)}", log_area)
        print_log(str(augments), log_area)


# ====================== 第三步：创建完整GUI（按钮+日志区域） ======================
def create_gui():
    # 1. 创建主窗口
    root = tk.Tk()
    root.title("LOL海克斯乱斗工具")
    root.geometry("800x400")  # 扩大窗口，容纳日志区域
    root.resizable(False, False)

    # 2. 创建按钮框架（放置两个功能按钮）
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)  # 垂直间距10像素

    # 按钮1：识别海克斯（绑定函数，传递日志区域）
    btn1 = tk.Button(
        btn_frame,
        text="识别英雄",
        command=lambda: recognize_champion(log_area),  # lambda传递参数给函数
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn1.grid(row=0, column=0, padx=20)  # 网格布局，水平间距20

    # 按钮2：导出数据
    btn2 = tk.Button(
        btn_frame,
        text="识别符文",
        command=lambda: recognize_augment(log_area),
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn2.grid(row=0, column=1, padx=20)

    # 3. 创建日志输出区域（带滚动条，只读）
    log_label = tk.Label(root, text="运行日志：", font=("微软雅黑", 10))
    log_label.pack(anchor="w", padx=20)  # 左对齐，水平间距20

    log_area = scrolledtext.ScrolledText(
        root,
        width=120,  # 宽度（字符数）
        height=15,  # 高度（行数）
        font=("Consolas", 9),  # 等宽字体，适合日志
        state=tk.DISABLED,  # 初始锁定，禁止编辑
    )
    log_area.pack(padx=20, pady=5)  # 边距

    # 初始化日志
    print_log("GUI已启动，等待执行操作...", log_area)

    # 4. 启动主循环
    root.mainloop()


# ====================== 运行GUI ======================
if __name__ == "__main__":
    setup_logging()
    create_gui()
