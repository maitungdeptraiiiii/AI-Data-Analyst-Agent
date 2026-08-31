# 📦 Output Assets for Project Report & Overleaf LaTeX

Thư mục này chứa toàn bộ các hình ảnh, số liệu và kết quả kiểm thử đã được chuẩn hóa để bạn chèn trực tiếp vào báo cáo, đồ án hoặc slide thuyết trình.

---

## 🖼️ Danh sách Hình ảnh (High-Resolution 300 DPI)

| Tên tệp | Mô tả | Mã LaTeX chèn vào Overleaf |
|---|---|---|
| `fig_pytest_result.png` | Ảnh chụp terminal: Kết quả chạy `pytest tests/` với **117/117 test cases pass (100%)** | `\includegraphics[width=0.95\textwidth]{output/fig_pytest_result.png}` |
| `fig_mypy_result.png` | Ảnh chụp terminal: Kết quả chạy `mypy --strict src eval` (0 lỗi / 56 files) và `ruff check` (0 cảnh báo) | `\includegraphics[width=0.85\textwidth]{output/fig_mypy_result.png}` |
| `fig_sample_chart.png` | Biểu đồ Matplotlib mẫu tỷ lệ 4:3: Phân tích doanh thu & lợi nhuận theo tháng kèm chú thích điểm sụt giảm tháng 7 | `\includegraphics[width=0.75\textwidth]{output/fig_sample_chart.png}` |

---

## 📄 Danh sách Tệp Dữ liệu & Kết quả Text

1. **`pytest_output.txt`**: Toàn bộ log text kết quả kiểm thử 13 test suites (117 tests).
2. **`mypy_ruff_output.txt`**: Log text kiểm tra kiểu nghiêm ngặt (mypy strict) và định dạng mã nguồn (ruff).
3. **`latest_eval_results.json`**: Kết quả định lượng chi tiết của **30 Golden Test Cases** trên 9 danh mục phân tích (100% Passed).
4. **`latest_eval_report.md`**: Báo cáo đánh giá tổng hợp định dạng Markdown.

---

## 📋 Mẫu mã LaTeX (Overleaf Snippet)

```latex
\begin{figure}[H]
\centering
\includegraphics[width=0.95\textwidth]{output/fig_pytest_result.png}
\caption{Kết quả kiểm thử tự động 117/117 unit tests đạt tỷ lệ thành công 100\%}
\label{fig:pytest_result}
\end{figure}

\begin{figure}[H]
\centering
\includegraphics[width=0.85\textwidth]{output/fig_mypy_result.png}
\caption{Kết quả kiểm tra kiểu dữ liệu tĩnh mypy strict mode và ruff linter}
\label{fig:mypy_result}
\end{figure}

\begin{figure}[H]
\centering
\includegraphics[width=0.75\textwidth]{output/fig_sample_chart.png}
\caption{Biểu đồ Matplotlib mẫu do hệ thống tự sinh biểu diễn xu hướng doanh thu và lợi nhuận}
\label{fig:sample_chart}
\end{figure}
```
