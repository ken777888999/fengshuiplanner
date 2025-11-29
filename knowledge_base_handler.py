import os
import glob
# import fitz  <-- 删除或注释掉这一行，你实际用的是 PyPDF2
import PyPDF2
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

class KnowledgeBaseHandler:
    def __init__(self, base_path="knowledge_base"):
        self.base_path = base_path
        self.books_content = {} # 缓存书籍内容，避免重复读取
        print(f"📚 初始化知识库，路径: {self.base_path}")

    def _clean_html(self, html_content):
        """从EPUB的HTML中提取纯文本"""
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)

    def _read_epub(self, file_path):
        """读取EPUB文件内容"""
        try:
            book = epub.read_epub(file_path)
            text_content = []
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    text_content.append(self._clean_html(item.get_content()))
            return " ".join(text_content)
        except Exception as e:
            print(f"❌ 读取 EPUB 失败 {file_path}: {e}")
            return ""

    def _read_pdf(self, file_path):
        """读取PDF文件内容"""
        try:
            text_content = []
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                # 为了性能，只读前50页或者每页提取，这里全读
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        text_content.append(text)
            return " ".join(text_content)
        except Exception as e:
            print(f"❌ 读取 PDF 失败 {file_path}: {e}")
            return ""

    def load_knowledge_base(self):
        """加载所有书籍到内存中 (只在启动时运行一次)"""
        # 查找所有 epub 和 pdf
        epub_files = glob.glob(os.path.join(self.base_path, "*.epub"))
        pdf_files = glob.glob(os.path.join(self.base_path, "*.pdf"))
        
        all_files = epub_files + pdf_files
        
        if not all_files:
            print("⚠️ 警告: 在 knowledge_base 文件夹中未找到任何书籍。")
            return

        print(f"📚 发现 {len(all_files)} 本书，开始加载...")
        
        for file_path in all_files:
            filename = os.path.basename(file_path)
            if filename in self.books_content:
                continue # 已经加载过
            
            print(f"   正在读取: {filename}...")
            if file_path.endswith('.epub'):
                content = self._read_epub(file_path)
            elif file_path.endswith('.pdf'):
                content = self._read_pdf(file_path)
            else:
                content = ""
            
            # 简单的预处理：去掉过多的换行符
            self.books_content[filename] = content.replace('\n', ' ')
        
        print("✅ 所有书籍加载完成！")

    def get_relevant_context(self, query, max_chars=3000):
        """
        根据用户的查询 (如 'bedroom', 'kitchen') 搜索书籍中的相关段落。
        这是一个简单的关键词搜索，避免发送整本书给 AI。
        """
        relevant_texts = []
        
        # 将查询拆分为关键词 (例如 "bedroom feng shui" -> ["bedroom", "feng", "shui"])
        # 这里简化处理，直接用整个词或者特定房间名
        keywords = [query.lower()]
        if "bedroom" in query.lower(): keywords.append("bed")
        if "kitchen" in query.lower(): keywords.append("stove")
        if "living" in query.lower(): keywords.append("sofa")
        
        for filename, content in self.books_content.items():
            # 简单的滑动窗口搜索或段落搜索
            # 这里我们寻找包含关键词的上下文片段
            content_lower = content.lower()
            
            for kw in keywords:
                start_index = content_lower.find(kw)
                while start_index != -1:
                    # 截取关键词前后的一段文字
                    start = max(0, start_index - 200)
                    end = min(len(content), start_index + 500)
                    snippet = content[start:end]
                    
                    relevant_texts.append(f"--- From book: {filename} ---\n...{snippet}...\n")
                    
                    # 限制数量，避免太多
                    if len(relevant_texts) > 3: 
                        break
                    
                    # 寻找下一个出现位置
                    start_index = content_lower.find(kw, start_index + 1000) # 跳过一段距离
                
                if len(relevant_texts) > 5: break
            if len(relevant_texts) > 5: break
            
        # 组合结果，并限制总长度
        final_context = "\n".join(relevant_texts)
        return final_context[:max_chars]

# 用于测试
if __name__ == "__main__":
    kb = KnowledgeBaseHandler()
    kb.load_knowledge_base()
    context = kb.get_relevant_context("bedroom")
    print("测试提取内容:", context[:500])
