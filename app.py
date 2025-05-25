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
# Użyjemy tego samego modelu do wszystkich interakcji
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Funkcje Asystenta ---

def describe_and_tag_image(image_bytes):
    """
    Opisuje zawartość zdjęcia i generuje tagi za pomocą Gemini 1.5 Flash.
    """
    image_part = {
        'mime_type': 'image/jpeg', # Dostosuj typ MIME jeśli potrzebujesz
        'data': image_bytes
    }
    
    prompt_parts = [
        "Opisz szczegółowo zawartość tego zdjęcia, koncentrując się na głównych obiektach, osobach, ilości i kolorze obiektów, akcjach, kolorach i ogólnym kontekście. Następnie, wygeneruj listę od 10 do 30 słów kluczowych (tagów) oddzielonych przecinkami, które najlepiej charakteryzują to zdjęcie. Format odpowiedzi: Opis: [Twój opis]. Tagi: [tag1, tag2, ...].",
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
        st.error(f"Wystąpił błąd podczas opisywania/tagowania zdjęcia: {e}. Spróbuj ponownie lub sprawdź status API.")
        return "Nie udało się opisać zdjęcia.", "Brak tagów."

def get_faq_context():
    """Generuje sformatowany kontekst FAQ."""
    faq_context = ""
    if FAQ_DATA:
        faq_context += "Kontekst FAQ:\n"
        for entry in FAQ_DATA:
            faq_context += f"Pytanie: {entry['pytanie']}\nOdpowiedź: {entry['odpowiedz']}\n---\n"
    else:
        faq_context = "Brak dostępnego kontekstu FAQ.\n"
    return faq_context

def get_image_context(description, tags):
    """Generuje sformatowany kontekst zdjęcia."""
    if description and tags:
        return f"\nKontekst zdjęcia:\nOpis: {description}\nTagi: {tags}\n"
    elif description:
        return f"\nKontekst zdjęcia:\nOpis: {description}\n"
    return ""


# --- Główna logika chatbota ---

def chat_with_bot():
    """
    Funkcja wywoływana po przesłaniu pytania lub wybraniu zdjęcia.
    Zarządza historią rozmowy i generuje odpowiedzi.
    """
    user_question = st.session_state.chat_input # Pobierz pytanie z pola tekstowego

    if user_question:
        # Dodaj pytanie użytkownika do historii rozmowy
        st.session_state.messages.append({"role": "user", "content": user_question})
        
        # Przygotuj kontekst dla modelu
        combined_context = get_faq_context() + get_image_context(
            st.session_state['image_description'],
            st.session_state['image_tags']
        )
        
        # Budowanie pełnego promptu dla modelu
        # Model Gemini przyjmuje listę obiektów (tekst, obraz, itp.) jako prompt.
        # W trybie konwersacji, będziemy używać obiektu ChatSession.
        
        # Inicjalizacja chat sesji (jeśli jeszcze jej nie ma)
        if 'chat_session' not in st.session_state:
            # Pierwsza wiadomość dla modelu - kontekst systemowy
            st.session_state.chat_session = model.start_chat(history=[
                {"role": "user", "parts": [
                    "Jesteś pomocnym asystentem AI. Odpowiadasz na pytania użytkownika, korzystając z kontekstu FAQ oraz/lub opisu i tagów przesłanego zdjęcia. Utrzymuj kontekst rozmowy. Jeśli pytanie nie pasuje do żadnego kontekstu, grzecznie poinformuj, że nie możesz pomóc i zaproponuj kontakt z obsługą klienta.",
                    combined_context
                ]},
                {"role": "model", "parts": ["Rozumiem. Jak mogę pomóc?"]}
            ])
        else:
            # Aktualizuj kontekst w historii czatu, jeśli zdjęcie zostało zmienione
            # lub jeśli dodajemy go po raz pierwszy do istniejącej sesji.
            # To jest uproszczenie; w bardziej złożonym czacie wymagałoby lepszego zarządzania kontekstem systemowym.
            if st.session_state.get('context_updated_flag', False) and 'chat_session' in st.session_state:
                # Jeśli kontekst się zmienił, możemy zresetować sesję lub sprytnie dodać kontekst.
                # Dla prostoty, w tej MVP wersji, jeśli kontekst obrazu się zmienia,
                # dodamy go jako nową "wiadomość" od systemu.
                # W praktyce, dla dłuższych rozmów, lepsze byłoby dynamiczne wstrzykiwanie do promptu systemowego
                # lub re-inicjalizacja sesji z nowym kontekstem systemowym.
                st.session_state.chat_session = model.start_chat(history=[
                    {"role": "user", "parts": [
                        "Jesteś pomocnym asystentem AI. Odpowiadasz na pytania użytkownika, korzystając z kontekstu FAQ oraz/lub opisu i tagów przesłanego zdjęcia. Utrzymuj kontekst rozmowy. Jeśli pytanie nie pasuje do żadnego kontekstu, grzecznie poinformuj, że nie możesz pomóc i zaproponuj kontakt z obsługi klienta.",
                        combined_context
                    ]},
                    {"role": "model", "parts": ["Rozumiem. Jak mogę pomóc?"]}
                ])
                st.session_state['context_updated_flag'] = False # Zresetuj flagę

        try:
            # Wysyłanie wiadomości do modelu w ramach sesji czatu
            with st.spinner("Myślę..."):
                response = st.session_state.chat_session.send_message(user_question)
                bot_response = response.text.strip()
            
            # Dodaj odpowiedź bota do historii rozmowy
            st.session_state.messages.append({"role": "assistant", "content": bot_response})
            
        except Exception as e:
            st.error(f"Wystąpił błąd podczas generowania odpowiedzi: {e}. Spróbuj zadać pytanie ponownie.")
            st.session_state.messages.append({"role": "assistant", "content": "Przepraszam, wystąpił problem z wygenerowaniem odpowiedzi. Spróbuj ponownie."})
        
        # Wyczyść pole wprowadzania po wysłaniu
        st.session_state.chat_input = ""
    else:
        st.session_state.messages.append({"role": "assistant", "content": "Wpisz coś, aby rozpocząć rozmowę."})


# --- Interfejs Streamlit ---

st.set_page_config(page_title="Asystent AI: Chatbot z FAQ i Zdjęciem", layout="centered")
st.title("🤖 Asystent AI: Chatbot z FAQ i Zdjęciem")
st.markdown("Witaj! Jestem chatbotem, który potrafi odpowiedzieć na pytania dotyczące naszego FAQ lub przesłanego obrazu, a także opisać i otagować zdjęcia. Możesz ze mną swobodnie rozmawiać!")

# Inicjalizacja zmiennych stanu sesji
if 'messages' not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Cześć! Jestem Twoim asystentem. Jak mogę pomóc?"}]
if 'image_description' not in st.session_state:
    st.session_state['image_description'] = None
if 'image_tags' not in st.session_state:
    st.session_state['image_tags'] = None
if 'uploaded_image_bytes' not in st.session_state:
    st.session_state['uploaded_image_bytes'] = None
if 'uploaded_file_id' not in st.session_state: # Do sprawdzania, czy to nowy plik
    st.session_state['uploaded_file_id'] = None
if 'chat_session' not in st.session_state:
    st.session_state['chat_session'] = None # Sesja czatu Gemini
if 'context_updated_flag' not in st.session_state:
    st.session_state['context_updated_flag'] = False # Flaga do sygnalizowania zmiany kontekstu

# Sekcja przesyłania zdjęć
st.header("📸 Prześlij Zdjęcie do Analizy")
uploaded_file = st.file_uploader("Wybierz zdjęcie (JPG, PNG):", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Sprawdź, czy przesłany plik jest inny niż poprzedni
    if st.session_state['uploaded_file_id'] != uploaded_file.file_id:
        st.session_state['uploaded_file_id'] = uploaded_file.file_id
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
            
            # Dodaj informację o zdjęciu do historii czatu
            st.session_state.messages.append({"role": "assistant", "content": f"Przeanalizowałem to zdjęcie: {description}. Tag: {tags}. Teraz możesz zadawać mi pytania na jego temat."})
            st.session_state['context_updated_flag'] = True # Ustaw flagę, że kontekst się zmienił
            st.rerun() # Odśwież aplikację, aby zaktualizować sesję czatu
    else: # Jeśli plik już był przesłany w tej sesji
        st.image(uploaded_file, caption='Przesłane zdjęcie', use_column_width=True)
        st.subheader("Opis zdjęcia:")
        st.write(st.session_state['image_description'])
        st.subheader("Słowa kluczowe (tagi):")
        st.code(st.session_state['image_tags'])

# Wyświetlanie historii rozmowy
st.header("💬 Rozmowa z Asystentem")
# Użyj iteratora od końca, aby nowe wiadomości były na dole (jak w prawdziwym czacie)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Pole wprowadzania pytania na dole
st.text_input(
    "Wpisz swoje pytanie (naciśnij Enter):", 
    key="chat_input", 
    on_change=chat_with_bot, # Ta funkcja zostanie wywołana po naciśnięciu Enter
    placeholder="Zapytaj o FAQ, zdjęcie lub cokolwiek..."
)

st.markdown("---")
st.markdown("Stworzone z ❤️ i **Google Cloud Platform (Gemini AI)**")