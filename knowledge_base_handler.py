import os
import logging
import fitz  # PyMuPDF
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import random

logger = logging.getLogger(__name__)

# 知识库路径
KNOWLEDGE_BASE_PATH = "knowledge_base/"

def read_pdf(file_path, max_pages=10):
    """读取PDF文件的前几页内容"""
    text = ""
    try:
        doc = fitz.open(file_path)
        # 读取前 max_pages 页，或者文档总页数，取较小值
        pages_to_read = min(max_pages, len(doc))
        
        for i in range(pages_to_read):
            text += doc[i].get_text()
            
        doc.close()
        logger.info(f"Successfully read PDF: {file_path}")
    except Exception as e:
        logger.error(f"Error reading PDF {file_path}: {str(e)}")
    return text

def read_epub(file_path, max_chars=5000):
    """读取EPUB文件的部分内容"""
    text = ""
    try:
        book = epub.read_epub(file_path)
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                # 使用BeautifulSoup去除HTML标签
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text() + "\n"
                # 限制长度，防止Token溢出
                if len(text) > max_chars: 
                    break
        logger.info(f"Successfully read EPUB: {file_path}")
    except Exception as e:
        logger.error(f"Error reading EPUB {file_path}: {str(e)}")
    return text

def extract_knowledge_for_prompt():
    """
    从知识库中提取相关信息以增强提示词
    """
    combined_knowledge = ""
    
    try:
        # 检查目录是否存在
        if not os.path.exists(KNOWLEDGE_BASE_PATH):
            logger.warning(f"Knowledge base directory not found: {KNOWLEDGE_BASE_PATH}")
            return "Feng Shui Principles: Ensure balance of Yin and Yang."

        files = [f for f in os.listdir(KNOWLEDGE_BASE_PATH) if f.endswith(('.pdf', '.epub'))]
        
        if not files:
            logger.warning("No PDF or EPUB files found in knowledge base.")
            return "Feng Shui Principles: Keep the bedroom clutter-free and ensure the bed has a solid wall behind it."

        # 遍历文件并读取内容
        # 注意：为了防止Prompt过长导致API报错或费用过高，我们限制每个文件的读取量
        for filename in files:
            file_path = os.path.join(KNOWLEDGE_BASE_PATH, filename)
            content = ""
            
            if filename.endswith('.pdf'):
                # 读取PDF，限制页数
                content = read_pdf(file_path, max_pages=5)
            elif filename.endswith('.epub'):
                # 读取EPUB，限制字符数
                content = read_epub(file_path, max_chars=3000)
            
            if content:
                # 清理多余空白字符
                content = " ".join(content.split())
                # 截取前2000个字符作为上下文
                excerpt = content[:2000]
                combined_knowledge += f"\n--- Reference from Book: {filename} ---\n{excerpt}...\n"

        if not combined_knowledge:
            return "Feng Shui Principles: Ensure good air flow and lighting."

        return f"Use the following knowledge from Feng Shui books to analyze the bedroom:\n{combined_knowledge}"

    except Exception as e:
        logger.error(f"Error in extract_knowledge_for_prompt: {str(e)}")
        # 发生错误时返回默认原则，保证程序不崩溃
        return "Feng Shui Principles: Bed placement is crucial. Avoid mirrors facing the bed."
