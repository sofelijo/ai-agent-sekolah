import pandas as pd
import os

files = [
    "/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/dashboard/library/data_buku/Data Buku Perpustakaan Atas.xlsx",
    "/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/dashboard/library/data_buku/Datar Buku Perpustakaan Bawah.xlsx"
]

for file_path in files:
    print(f"--- Inspecting {os.path.basename(file_path)} ---")
    try:
        # Read all sheets
        xl = pd.ExcelFile(file_path)
        print(f"Sheets: {xl.sheet_names}")
        
        for sheet in xl.sheet_names:
            print(f"\nSheet: {sheet}")
            df = pd.read_excel(file_path, sheet_name=sheet, header=None, nrows=20)
            
            # Search for header row
            header_row_idx = -1
            for idx, row in df.iterrows():
                row_str = row.astype(str).str.lower().tolist()
                if any("judul" in s for s in row_str) or any("nama buku" in s for s in row_str):
                    header_row_idx = idx
                    print(f"Found header at row {idx}: {row.tolist()}")
                    break
            
            if header_row_idx != -1:
                # Read again with header
                df = pd.read_excel(file_path, sheet_name=sheet, header=header_row_idx, nrows=10)
                print("Columns found:", df.columns.tolist())
                print("First 5 rows of data:")
                print(df.head(5).to_string())
            else:
                print("Header not found in first 20 rows.")
                print(df.to_string())
            
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    print("\n" + "="*30 + "\n")
