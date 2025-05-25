import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import json

# --- Konfiguracja API i FAQ ---
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

# Inicjalizacja modelu Gemini 1.5 Flash (dla obrazów i tekstu)
# Ten model jest multimodalny i może przyjmować zarówno obrazy, jak i tekst.
# Jest to optymalne rozwiązanie dla tego projektu.
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Funkcje asystenta ---

def describe_and_tag_image(image_bytes):
    """
    Opisuje zawartość zdjęcia i generuje tagi za pomocą Gemini 1.5 Flash.
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
        response = model.generate_content(prompt_parts)
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
        else:
            description = text_response
            if len(description.split()) > 5:
                potential_tags = [word.strip(",.") for word in description.lower().split() if len(word) > 2 and word not in ["a", "an", "the", "is", "are", "on", "in", "of", "with", "and", "or", "dla", "do", "na", "w", "z"]]
                tags = ", ".join(list(set(potential_tags[:10])))
            else:
                tags = "Brak wyraźnych tagów."

        return description, tags
    except Exception as e:
        st.error(f"Wystąpił błąd podczas opisywania/tagowania zdjęcia: {e}. Sprawdź, czy Twój klucz API jest prawidłowy i czy nie przekroczyłeś limitów usage.")
        return "Nie udało się opisać zdjęcia. Spróbuj ponownie.", "Brak tagów."

def answer_question(user_question, image_description=None, image_tags=None):
    """
    Odpowiada na pytanie użytkownika, uwzględniając kontekst FAQ i/lub zdjęcie.
    """
    # Przygotuj kontekst FAQ
    faq_context = ""
    if FAQ_DATA:
        faq_context += "Kontekst FAQ:\n"
        for entry in FAQ_DATA:
            faq_context += f"Pytanie: {entry['pytanie']}\nOdpowiedź: {entry['odpowiedz']}\n---\n"
    else:
        faq_context = "Brak dostępnego kontekstu FAQ.\n"

    # Przygotuj kontekst zdjęcia, jeśli jest dostępny
    image_context = ""
    if image_description and image_tags:
        image_context = f"\nKontekst zdjęcia:\nOpis: {image_description}\nTagi: {image_tags}\n"
    elif image_description:
        image_context = f"\nKontekst zdjęcia:\nOpis: {image_description}\n"
    
    # Budowanie promptu
    prompt = f"""
    Jesteś asystentem, który odpowiada na pytania użytkownika.
    Twoja odpowiedź powinna być oparta na dostarczonym kontekście FAQ oraz/lub opisie przesłanego zdjęcia.
    Jeśli pytanie dotyczy zdjęcia, odwołaj się do jego opisu.
    Jeśli pytanie dotyczy FAQ, odwołaj się do kontekstu FAQ.
    Jeśli pytanie nie pasuje do żadnego z kontekstów, odpowiedz, że nie możesz pomóc z tym pytaniem i zaproponuj kontakt z obsługą klienta.

    {faq_context}
    {image_context}

    Pytanie użytkownika: {user_question}
    Odpowiedź:
    """
    
    try:
        # Wysyłamy tylko tekstowy prompt, ponieważ obraz został już przetworzony na opis.
        # Jeśli chcielibyśmy, żeby LLM "widział" obraz przy każdym pytaniu,
        # musielibyśmy przekazywać go w każdym zapytaniu, co zwiększyłoby koszty/opóźnienia.
        # Dla tego scenariusza, opis tekstowy jest wystarczającym kontekstem.
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.error(f"Wystąpił błąd podczas odpowiadania na pytanie: {e}. Spróbuj zadać pytanie ponownie.")
        return "Nie udało się udzielić odpowiedzi na pytanie z powodu błędu."

# --- Interfejs Streamlit ---

st.set_page_config(page_title="Asystent AI: Opis i FAQ", layout="centered")
st.title("🤖 Asystent AI: Opis Zdjęć i FAQ (wersja multimodalna)")
st.markdown("Witaj! Jestem asystentem, który potrafi opisać i otagować przesłane zdjęcia, a także odpowiedzieć na pytania dotyczące naszego FAQ lub przesłanego obrazu.")

# Zmienne stanu sesji do przechowywania opisu i tagów zdjęcia
if 'image_description' not in st.session_state:
    st.session_state['image_description'] = None
if 'image_tags' not in st.session_state:
    st.session_state['image_tags'] = None
if 'uploaded_image_bytes' not in st.session_state:
    st.session_state['uploaded_image_bytes'] = None


# Sekcja opisywania zdjęć
st.header("📸 Prześlij i Otaguj Zdjęcie")
uploaded_file = st.file_uploader("Wybierz zdjęcie (JPG, PNG) do analizy:", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Tylko jeśli przesłano nowy plik, przetwarzaj go
    if st.session_state['uploaded_image_bytes'] != uploaded_file.getvalue():
        st.session_state['uploaded_image_bytes'] = uploaded_file.getvalue()
        
        st.image(uploaded_file, caption='Przesłane zdjęcie', use_column_width=True)
        image_bytes = uploaded_file.getvalue()
        
        with st.spinner("Analizuję zdjęcie za pomocą Gemini AI..."):
            description, tags = describe_and_tag_image(image_bytes)
            st.session_state['image_description'] = description
            st.session_state['image_tags'] = tags
            st.subheader("Opis zdjęcia:")
            st.write(st.session_state['image_description'])
            st.subheader("Słowa kluczowe (tagi):")
            st.code(st.session_state['image_tags'])
    else: # Jeśli plik już był przesłany, po prostu go wyświetl
        st.image(uploaded_file, caption='Przesłane zdjęcie', use_column_width=True)
        st.subheader("Opis zdjęcia:")
        st.write(st.session_state['image_description'])
        st.subheader("Słowa kluczowe (tagi):")
        st.code(st.session_state['image_tags'])

# Sekcja zadawania pytań
st.header("❓ Zadaj Pytanie")
st.markdown("Zadaj pytanie dotyczące **FAQ** lub **przesłanego zdjęcia** (jeśli zostało przeanalizowane).")
user_question = st.text_input("Wpisz swoje pytanie tutaj:", key="general_question_input")

if user_question:
    if st.button("Zadaj pytanie"):
        with st.spinner("Szukam odpowiedzi..."):
            answer = answer_question(
                user_question,
                image_description=st.session_state['image_description'],
                image_tags=st.session_state['image_tags']
            )
            st.subheader("Odpowiedź:")
            st.info(answer)

st.markdown("---")
