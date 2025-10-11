# test_pywinctl.py
import pywinctl as pwc
import time

def test_window_detection():
    """測試 PyWinCtl 的視窗偵測能力"""
    print("=" * 60)
    print("PyWinCtl 視窗偵測測試")
    print("=" * 60)
    
    # 獲取所有視窗
    all_windows = pwc.getAllWindows()
    print(f"\n找到 {len(all_windows)} 個視窗\n")
    
    # 顯示所有視窗標題
    for i, window in enumerate(all_windows, 1):
        if window.title:  # 只顯示有標題的視窗
            print(f"{i:03d}: 「{window.title}」")
            # 顯示更多資訊
            print(f"      可見: {window.isVisible}, 最小化: {window.isMinimized}")
            print(f"      位置: ({window.left}, {window.top}), 大小: {window.width}x{window.height}")
            print()
    
    # 特別查找特定視窗
    print("\n" + "=" * 60)
    print("查找特定視窗：")
    
    # 使用不同的搜尋條件
    search_terms = ["待辦事項", "待辦", "事項", "應用程式", "flask"]
    
    for term in search_terms:
        # 使用 CONTAINS 條件進行搜尋
        found = pwc.getWindowsWithTitle(
            term, 
            condition=pwc.Re.CONTAINS,
            flags=pwc.Re.IGNORECASE
        )
        if found:
            print(f"✓ 找到包含 '{term}' 的視窗: {found[0].title}")
        else:
            print(f"✗ 未找到包含 '{term}' 的視窗")

if __name__ == "__main__":
    test_window_detection()
    
    print("\n每 3 秒更新一次，按 Ctrl+C 結束...")
    try:
        while True:
            time.sleep(3)
            test_window_detection()
    except KeyboardInterrupt:
        print("\n程式已停止")