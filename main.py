import os
import pandas as pd
from parser import pdf_parser
from extract_data import extract_acordao_data

def build_dataframe(diretorio):
    data = []

    for raiz, _, arquivos in os.walk(diretorio):
        for arquivo in arquivos:
            if arquivo.lower().endswith(".pdf"):
                text = pdf_parser(os.path.join(raiz, arquivo))
                acordao_data = extract_acordao_data(text)
                data.append(acordao_data)

    df = pd.DataFrame(data)

    return df

# Exemplo de uso:
if __name__ == "__main__":
    df = build_dataframe('./data/')
    df.to_csv('acordaos.csv')