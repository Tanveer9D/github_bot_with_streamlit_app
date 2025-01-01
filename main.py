import os
import requests
import streamlit as st
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.vectorstores import FAISS
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chains import RetrievalQA

# Load environment variables
load_dotenv()

# Constants
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ORG_NAME = os.getenv("ORG_NAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# Headers for GitHub API
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

# Initialize LangChain ChatOpenAI
chat = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model="gpt-4o")
embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)

def fetch_repositories():
    url = f"https://api.github.com/orgs/{ORG_NAME}/repos"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def fetch_repo_content(repo_name):
    url = f"https://api.github.com/repos/{ORG_NAME}/{repo_name}/contents"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def analyze_file_in_chunks(file_url, chunk_size=1000):
    """Fetch and analyze file content in manageable chunks."""
    file_response = requests.get(file_url, headers=HEADERS)
    if file_response.status_code == 200:
        content = file_response.text
        lines = content.splitlines()
        line_count = len(lines)
        analysis = []

        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i:i + chunk_size])
            system_message = SystemMessagePromptTemplate.from_template(
                "You are a helpful assistant summarizing file content and structure."
            )
            human_message = HumanMessagePromptTemplate.from_template(
                """
                Analyze the following code file chunk and extract:
                - Key functions and methods.
                - Main purpose of this chunk.
                - Any comments or inline documentation.
                - Dependencies or imports used.
                Content: {chunk_content}
                """
            )
            prompt_template = ChatPromptTemplate.from_messages([system_message, human_message])
            prompt = prompt_template.format_messages(chunk_content=chunk)
            response = chat(messages=prompt)
            analysis.append(response.content)

        combined_analysis = "\n".join(analysis)
        return line_count, combined_analysis
    return 0, "Failed to fetch file content."

def analyze_repository_content(repo_name, repo_content, max_files=10):
    """Analyze repository content while limiting the number of files."""
    total_files = 0
    total_lines = 0
    file_analysis = []

    for item in repo_content[:max_files]:
        if item["type"] == "file":
            total_files += 1
            file_name = item["name"]
            line_count, analysis = analyze_file_in_chunks(item["download_url"])
            total_lines += line_count
            file_analysis.append(f"File: {file_name}\nLines: {line_count}\nAnalysis:\n{analysis}\n")

    return total_files, total_lines, file_analysis

def create_vector_store(analyses):
    """Create a FAISS vector store from the repository analyses."""
    documents = [
        {
            "content": analysis,
            "metadata": {"repo": analysis.split('\n')[0].split(': ')[1]}
        }
        for analysis in analyses
    ]
    texts = [doc["content"] for doc in documents]
    metadatas = [doc["metadata"] for doc in documents]
    vector_store = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
    return vector_store

def chat_with_vector_store(vector_store, query):
    """Create a chatbot using the FAISS vector store."""
    retriever = vector_store.as_retriever()
    qa_chain = RetrievalQA.from_chain_type(
        llm=chat,
        retriever=retriever,
        chain_type="stuff",
        return_source_documents=True
    )
    response = qa_chain({"query": query})
    result = response.get("result", "No result found.")
    source_documents = response.get("source_documents", [])
    sources = [
        {
            "repo": doc.metadata.get("repo"),
            "snippet": doc.page_content[:200].replace("\n", " ")
        }
        for doc in source_documents
    ]
    return result, sources

def main():
    st.title("GitHub Repository Analyzer and Chatbot")

    if "vector_store" not in st.session_state:
        st.session_state.vector_store = None

    if st.button("Fetch and Analyze Repositories"):
        repositories = fetch_repositories()
        analyses = []

        for repo in repositories:
            repo_name = repo["name"]
            repo_content = fetch_repo_content(repo_name)
            _, _, file_analysis = analyze_repository_content(repo_name, repo_content)
            analyses.extend(file_analysis)

        st.session_state.vector_store = create_vector_store(analyses)
        st.success("Repositories analyzed and vector store created.")

    if st.session_state.vector_store:
        user_query = st.text_input("Ask a question about the repositories:")
        if user_query:
            result, sources = chat_with_vector_store(st.session_state.vector_store, user_query)
            st.write("### Bot Response")
            st.write(result)
            # if sources:
            #     st.write("### Sources")
            #     for source in sources:
            #         st.write(f"- {source['repo']}: {source['snippet']}...")

if __name__ == "__main__":
    main()
