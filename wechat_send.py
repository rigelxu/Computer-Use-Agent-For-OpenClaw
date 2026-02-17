"""
微信发送文件/图片脚本 - 纯 pyautogui 实现，不依赖 CUA agent
用法: python wechat_send.py --contact "联系人名" --file "文件路径"
"""
import argparse
import time
import subprocess
import sys
import pyautogui
import pyperclip

pyautogui.FAILSAFE = False


def copy_file_to_clipboard(file_path: str):
    """用 PowerShell 把文件复制到系统剪贴板"""
    ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$file = New-Object System.Collections.Specialized.StringCollection
$file.Add('{file_path}')
[System.Windows.Forms.Clipboard]::SetFileDropList($file)
'''
    result = subprocess.run(
        ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to copy file to clipboard: {result.stderr}")
        sys.exit(1)
    print(f"File copied to clipboard: {file_path}")


def main():
    parser = argparse.ArgumentParser(description="微信发送文件/图片")
    parser.add_argument("--contact", required=True, help="联系人名字")
    parser.add_argument("--file", required=True, help="文件路径")
    parser.add_argument("--delay", type=float, default=1.5, help="步骤间延迟秒数")
    args = parser.parse_args()

    delay = args.delay

    print(f"=== 微信发送文件 ===")
    print(f"联系人: {args.contact}")
    print(f"文件: {args.file}")
    print()

    # Step 1: 点击任务栏微信图标调出窗口
    print("[1/7] 点击任务栏微信图标...")
    # 微信图标大约在任务栏中间偏右，y=1060 是任务栏位置
    # 先用 Alt+Tab 或直接点任务栏
    pyautogui.hotkey('alt', 'tab')
    time.sleep(0.5)
    # 点击任务栏微信图标（需要根据实际位置调整）
    pyautogui.click(1231, 1060)
    time.sleep(delay)

    # Step 2: 点击搜索框
    print("[2/7] 点击搜索框...")
    # 微信搜索框在窗口左上角
    pyautogui.click(454, 200)
    time.sleep(delay)

    # Step 3: 粘贴联系人名字
    print("[3/7] 粘贴联系人名字...")
    pyperclip.copy(args.contact)
    time.sleep(0.3)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(delay * 2)  # 等搜索结果出来

    # Step 4: 按回车选择第一个搜索结果
    print("[4/7] 选择搜索结果...")
    pyautogui.press('enter')
    time.sleep(delay)

    # Step 5: 点击聊天输入框
    print("[5/7] 点击聊天输入框...")
    # 微信聊天输入框大约在窗口底部中间
    pyautogui.click(1100, 900)
    time.sleep(delay)

    # Step 6: 把文件复制到剪贴板，然后 Ctrl+V 粘贴
    print("[6/7] 粘贴文件...")
    copy_file_to_clipboard(args.file)
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(delay * 2)  # 等图片加载

    # Step 7: 点击发送按钮（微信粘贴文件后弹确认框，回车不管用，需要点发送按钮）
    print("[7/7] 点击发送按钮...")
    # 微信文件确认框的"发送(S)"按钮位置
    pyautogui.click(1615, 926)
    time.sleep(delay)

    print()
    print("=== 完成 ===")
    print("请检查微信确认是否发送成功")


if __name__ == "__main__":
    main()
