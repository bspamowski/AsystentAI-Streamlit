import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import json

# --- Konfiguracja API i FAQ ---
# Aby klucz API był bezpieczny, przechowaj go w pliku .streamlit/secrets.toml
# Przykład zawartości .streamlit/secrets.toml:
# GOOGLE_API_KEY = "AIzaSy..." # Twój klucz API Google Gemini

try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("Błąd konfiguracji: Klucz API Google Gemini (GOOGLE_API_KEY) nie został znaleziony w pliku .streamlit/secrets.toml. "
             "Upewnij się, że plik istnieje i zawiera poprawny klucz.")
    st.stop()
except Exception as e:
    st.error(f"Wystąpił błąd podczas konfiguracji API Gemini: {e}")
    st.stop()


# Wczytaj FAQ
try:
    with open("faq.json", "r", encoding="utf-8") as f:
        FAQ_DATA = json.load(f)
except FileNotFoundError:
    st.error("Błąd: Plik 'faq.json' nie został znaleziony. Upewnij się, że znajduje się w tym samym katalogu co 'app.py'.")
    FAQ_DATA = []
except json.JSONDecodeError:
    st.error("Błąd: Plik 'faq.json' jest niepoprawnie sformatowany (nie jest prawidłowym JSON-em).")
    FAQ_DATA = []

# Inicjalizacja modeli Gemini
# Model dla obrazów
model_vision = genai.GenerativeModel('gemini-pro-vision')
# Model dla tekstu (FAQ)
model_text = genai.GenerativeModel('gemini-pro')

# --- Funkcje asystenta ---

def describe_and_tag_image(image_bytes):
    """
    Opisuje zawartość zdjęcia i generuje tagi za pomocą Gemini Pro Vision.
    """
    image_part = {
        'mime_type': 'image/jpeg', # Dostosuj typ MIME jeśli potrzebujesz (np. 'image/png')
        'data': image_bytes
    }
    
    prompt_parts = [
        "Opisz szczegółowo zawartość tego zdjęcia, koncentrując się na głównych obiektach, osobach, akcjach, kolorach i ogólnym kontekście. Następnie, wygeneruj listę od 5 do 10 słów kluczowych (tagów) oddzielonych przecinkami, które najlepiej charakteryzują to zdjęcie. Format odpowiedzi: Opis: [Twój opis]. Tagi: [tag1, tag2, ...].",
        image_part
    ]
    
    try:
        response = model_vision.generate_content(prompt_parts)
        text_response = response.text.strip()
        
        description = "Brak opisu."
        tags = "Brak tagów."
        
        if "Opis:" in text_response and "Tagi:" in text_response:
            parts = text_response.split("Tagi:", 1)
            description = parts[0].replace("Opis:", "").strip()
            tags = parts[1].strip()
        elif "Opis:" in text_response:
            description = text_response.replace("Opis:", "").strip()
        elif "Tagi:" in text_response:
             tags = text_response.replace("Tagi:", "").strip()
        else: # Jeśli format odpowiedzi nie pasuje dokładnie
            description = text_response # Użyj całej odpowiedzi jako opisu
            # Spróbuj wygenerować tagi z opisu, jeśli nie zostały wyraźnie wydzielone
            if len(description.split()) > 5: # Proste sprawdzenie, czy opis jest wystarczająco długi
                # Prosta ekstrakcja słów kluczowych (można ulepszyć)
                potential_tags = [word.strip(",.") for word in description.lower().split() if len(word) > 2 and word not in ["a", "an", "the", "is", "are", "on", "in", "of", "with", "and", "or", "dla", "do", "na", "w", "z"]]
                tags = ", ".join(list(set(potential_tags[:10]))) # Maksymalnie 10 unikalnych tagów
            else:
                tags = "Brak wyraźnych tagów."

        return description, tags
    except Exception as e:
        st.error(f"Wystąpił błąd podczas opisywania/tagowania zdjęcia: {e}. Sprawdź, czy Twój klucz API jest prawidłowy i czy nie przekroczyłeś limitów usage.")
        return "Nie udało się opisać zdjęcia. Spróbuj ponownie.", "Brak tagów."

def answer_faq(user_question):
    """
    Odpowiada na pytanie użytkownika na podstawie pliku FAQ, wykorzystując Gemini Pro.
    """
    if not FAQ_DATA:
        return "Przepraszamy, plik FAQ jest pusty lub nie został załadowany poprawnie. Nie mogę udzielić odpowiedzi."

    # Przygotuj kontekst dla LLM z pytaniami i odpowiedziami z FAQ
    faq_context = ""
    for entry in FAQ_DATA:
        faq_context += f"Pytanie: {entry['pytanie']}\nOdpowiedź: {entry['odpowiedz']}\n---\n"

    prompt = f"""
    Jesteś asystentem, który odpowiada na pytania wyłącznie na podstawie dostarczonego kontekstu FAQ.
    Przeczytaj uważnie kontekst FAQ przed udzieleniem odpowiedzi.
    Jeśli pytanie użytkownika nie pasuje do żadnej z odpowiedzi w FAQ lub kontekst nie zawiera wystarczających informacji, odpowiedz, że nie możesz pomóc z tym pytaniem i zaproponuj kontakt z obsługą klienta.

    Kontekst FAQ:
    {faq_context}

    Pytanie użytkownika: {user_question}
    Odpowiedź:
    """
    
    try:
        response = model_text.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.error(f"Wystąpił błąd podczas odpowiadania na pytanie FAQ: {e}. Spróbuj zadać pytanie ponownie.")
        return "Nie udało się udzielić odpowiedzi na pytanie z powodu błędu."

# --- Interfejs Streamlit ---

st.set_page_config(page_title="Asystent AI: Opis i FAQ", layout="centered")
st.title("🤖 Asystent AI: Opis Zdjęć i FAQ")
st.markdown("Witaj! Jestem asystentem, który potrafi opisać i otagować przesłane zdjęcia, a także odpowiedzieć na proste pytania z naszego FAQ.")

# Sekcja opisywania zdjęć
st.header("📸 Opisz i Otaguj Zdjęcie")
uploaded_file = st.file_uploader("Prześlij zdjęcie (JPG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Wyświetl przesłane zdjęcie
    st.image(uploaded_file, caption='Przesłane zdjęcie', use_column_width=True)
    
    # Konwertuj obraz do bajtów
    image_bytes = uploaded_file.getvalue()

    if st.button("Opisz i otaguj to zdjęcie"):
        with st.spinner("Analizuję zdjęcie za pomocą Gemini AI..."):
            description, tags = describe_and_tag_image(image_bytes)
            st.subheader("Opis zdjęcia:")
            st.write(description)
            st.subheader("Słowa kluczowe (tagi):")
            st.code(tags) # Używamy st.code dla lepszej czytelności tagów

# Sekcja FAQ
st.header("❓ Zadaj Pytanie (FAQ)")
user_question = st.text_input("Wpisz swoje pytanie dotyczące sklepu lub produktów:", key="faq_question_input")

if user_question:
    if st.button("Zadaj pytanie o FAQ"):
        with st.spinner("Szukam odpowiedzi w FAQ..."):
            answer = answer_faq(user_question)
            st.subheader("Odpowiedź:")
            st.info(answer)

st.markdown("---")
st.markdown("Stworzone z ❤️ i **Google Cloud Platform (Gemini AI)**")