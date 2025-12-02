import pandas as pd
import os
import re
from dashboard.db_access import get_cursor

# File paths
FILES = [
    "/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/dashboard/library/data_buku/Data Buku Perpustakaan Atas.xlsx",
    "/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/dashboard/library/data_buku/Datar Buku Perpustakaan Bawah.xlsx"
]

def get_next_book_code():
    with get_cursor() as cur:
        cur.execute("""
            SELECT MAX(CAST(code AS INTEGER)) 
            FROM books 
            WHERE code ~ '^[0-9]+$'
        """)
        row = cur.fetchone()
        max_code = row[0] if row and row[0] is not None else 0
        return max_code + 1

def add_book_with_items(title, author, publisher, year, code, stock, location):
    with get_cursor(commit=True) as cur:
        # Insert book
        cur.execute("""
            INSERT INTO books (title, author, publisher, year, code, stock, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (title, author, publisher, year, code, stock, location))
        book_id = cur.fetchone()[0]
        
        # Create items
        for i in range(stock):
            qr_code = f"{code}-{i+1}"
            cur.execute("""
                INSERT INTO book_items (book_id, qr_code, status)
                VALUES (%s, %s, 'available')
            """, (book_id, qr_code))
        return book_id

def clean_sheet_name(sheet_name):
    # Normalize "RAK1" to "Rak 1"
    match = re.match(r"([a-zA-Z]+)(\d+)", sheet_name)
    if match:
        return f"{match.group(1).capitalize()} {match.group(2)}"
    return sheet_name.capitalize()

def process_dataframe(df, location_prefix, sheet_name):
    # Search for header row
    header_row_idx = -1
    for idx, row in df.iterrows():
        row_str = row.astype(str).str.lower().tolist()
        if any("judul" in s for s in row_str) or any("nama buku" in s for s in row_str):
            header_row_idx = idx
            break
    
    if header_row_idx == -1:
        print(f"  [WARN] No header found in {sheet_name}, skipping.")
        return 0

    # Reload with correct header
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row_idx)
    
    # Identify columns based on keywords
    cols = df.columns.tolist()
    
    # Helper to find col index
    def find_col(keywords, columns):
        for i, col in enumerate(columns):
            col_str = str(col).lower()
            if any(k in col_str for k in keywords):
                return i
        return -1

    # We might have two tables side-by-side.
    # Let's try to split them.
    # Table 1: usually indices 0-5
    # Table 2: usually indices 9-13 (if exists)
    
    tables = []
    
    # Check for first table
    t1_cols = cols[0:8] # heuristic range
    if find_col(['judul', 'nama buku'], t1_cols) != -1:
        tables.append(df.iloc[:, 0:8])
        
    # Check for second table
    if len(cols) > 8:
        t2_cols = cols[9:] # heuristic range
        if find_col(['judul', 'nama buku'], t2_cols) != -1:
            tables.append(df.iloc[:, 9:])

    count = 0
    current_code = get_next_book_code()
    
    cleaned_sheet = clean_sheet_name(sheet_name)
    full_location = f"{location_prefix} - {cleaned_sheet}"

    for table_df in tables:
        # Map columns for this table slice
        table_cols = table_df.columns.tolist()
        
        idx_title = find_col(['judul', 'nama buku'], table_cols)
        idx_year = find_col(['tahun'], table_cols)
        idx_pub = find_col(['penerbit'], table_cols)
        idx_stock = find_col(['jumlah'], table_cols)
        
        if idx_title == -1:
            continue
            
        for _, row in table_df.iterrows():
            try:
                title = row.iloc[idx_title]
                if pd.isna(title) or str(title).strip() == "":
                    continue
                
                title = str(title).strip()
                
                year = row.iloc[idx_year] if idx_year != -1 else None
                try:
                    year = int(float(year)) if pd.notna(year) else 0
                except:
                    year = 0
                    
                publisher = row.iloc[idx_pub] if idx_pub != -1 else ""
                if pd.isna(publisher): publisher = ""
                publisher = str(publisher).strip()
                
                stock = row.iloc[idx_stock] if idx_stock != -1 else 1
                try:
                    stock = int(float(stock)) if pd.notna(stock) else 1
                except:
                    stock = 1
                
                # Author is empty as per plan
                author = ""
                
                # Add to DB
                add_book_with_items(title, author, publisher, year, str(current_code), stock, full_location)
                current_code += 1
                count += 1
                print(f"    Imported: {title} ({stock})")
                
            except Exception as e:
                print(f"    [ERROR] Failed to import row: {e}")
                
    return count

if __name__ == "__main__":
    total_imported = 0
    
    for file_path in FILES:
        filename = os.path.basename(file_path)
        print(f"Processing {filename}...")
        
        location_prefix = "Perpus Atas" if "Atas" in filename else "Perpus Bawah"
        
        try:
            xl = pd.ExcelFile(file_path)
            for sheet in xl.sheet_names:
                print(f"  Sheet: {sheet}")
                # Read raw first to find header
                df_raw = pd.read_excel(file_path, sheet_name=sheet, header=None, nrows=20)
                
                # Pass file_path to process_dataframe to re-read with correct header
                # Wait, process_dataframe needs to re-read. Let's refactor slightly or just pass file_path/sheet
                
                # Actually, let's just pass the raw df to find header index, then re-read inside the loop?
                # No, easier to just do the logic here or pass file path.
                
                # Let's fix process_dataframe signature to take file_path and sheet_name
                # But I defined it to take df. Let's change it.
                pass 
                
        except Exception as e:
            print(f"Error processing file {filename}: {e}")

    # Re-defining main loop to be cleaner
    print("\n--- Starting Import ---\n")
    
    for file_path in FILES:
        filename = os.path.basename(file_path)
        print(f"Processing {filename}...")
        location_prefix = "Perpus Atas" if "Atas" in filename else "Perpus Bawah"
        
        try:
            xl = pd.ExcelFile(file_path)
            for sheet in xl.sheet_names:
                print(f"  Sheet: {sheet}")
                # Read a bit to find header
                df_peek = pd.read_excel(file_path, sheet_name=sheet, header=None, nrows=20)
                
                # Find header index
                header_row_idx = -1
                for idx, row in df_peek.iterrows():
                    row_str = row.astype(str).str.lower().tolist()
                    if any("judul" in s for s in row_str) or any("nama buku" in s for s in row_str):
                        header_row_idx = idx
                        break
                
                if header_row_idx == -1:
                    print(f"    [WARN] No header found in {sheet}, skipping.")
                    continue

                # Read full sheet with header
                df = pd.read_excel(file_path, sheet_name=sheet, header=header_row_idx)
                
                # Identify columns
                cols = df.columns.tolist()
                
                def find_col(keywords, columns):
                    for i, col in enumerate(columns):
                        col_str = str(col).lower()
                        if any(k in col_str for k in keywords):
                            return i
                    return -1

                tables = []
                # Table 1
                t1_cols = cols[0:8]
                if find_col(['judul', 'nama buku'], t1_cols) != -1:
                    tables.append(df.iloc[:, 0:8])
                
                # Table 2
                if len(cols) > 8:
                    t2_cols = cols[9:]
                    if find_col(['judul', 'nama buku'], t2_cols) != -1:
                        tables.append(df.iloc[:, 9:])
                
                cleaned_sheet = clean_sheet_name(sheet)
                full_location = f"{location_prefix} - {cleaned_sheet}"
                
                sheet_count = 0
                
                for table_df in tables:
                    table_cols = table_df.columns.tolist()
                    idx_title = find_col(['judul', 'nama buku'], table_cols)
                    idx_year = find_col(['tahun'], table_cols)
                    idx_pub = find_col(['penerbit'], table_cols)
                    idx_stock = find_col(['jumlah'], table_cols)
                    
                    if idx_title == -1: continue
                    
                    for _, row in table_df.iterrows():
                        try:
                            title = row.iloc[idx_title]
                            if pd.isna(title) or str(title).strip() == "": continue
                            title = str(title).strip()
                            
                            year = row.iloc[idx_year] if idx_year != -1 else None
                            try: year = int(float(year)) if pd.notna(year) else 0
                            except: year = 0
                            
                            publisher = row.iloc[idx_pub] if idx_pub != -1 else ""
                            if pd.isna(publisher): publisher = ""
                            publisher = str(publisher).strip()
                            
                            stock = row.iloc[idx_stock] if idx_stock != -1 else 1
                            try: stock = int(float(stock)) if pd.notna(stock) else 1
                            except: stock = 1
                            
                            author = ""
                            
                            current_code = get_next_book_code() # Get fresh code each time to be safe
                            add_book_with_items(title, author, publisher, year, str(current_code), stock, full_location)
                            sheet_count += 1
                            total_imported += 1
                            
                        except Exception as e:
                            print(f"    [ERROR] Failed row: {e}")
                            
                print(f"    Imported {sheet_count} books from {sheet}")
                
        except Exception as e:
            print(f"Error processing file {filename}: {e}")
            
    print(f"\nTotal Imported: {total_imported}")
