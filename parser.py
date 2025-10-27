from PyPDF2 import PdfReader

def pdf_parser(pdf_path):
    """
    Extrai o texto de um arquivo PDF.

    Parâmetros:
        pdf_path (str): Caminho para o arquivo PDF.

    Retorna:
        str: Texto completo extraído do PDF.
    """
    texto = ""
    with open(pdf_path, "rb") as arquivo:
        leitor = PdfReader(arquivo)
        for pagina in leitor.pages:
            texto += pagina.extract_text() or ""
    return texto