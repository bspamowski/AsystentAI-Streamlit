import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import json

# --- Konfiguracja API ---
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("Błąd konfiguracji: Klucz API Google Gemini (GOOGLE_API_KEY) nie został znaleziony w pliku .streamlit/secrets.toml. "
             "Upewnij się, że plik istnieje i zawiera poprawny klucz.")
    st.stop()
except Exception as e:
    st.error(f"Wystąpił błąd podczas konfiguracji API Gemini: {e}")
    st.stop()

# Inicjalizacja modelu Gemini 1.5 Flash (dla obrazów i tekstu)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Funkcje parsowania FAQ ---

def parse_faq_text(file_content):
    """
    Parsuje prosty plik tekstowy FAQ na listę słowników.
    Oczekuje formatu: Pytanie, nowa linia, Odpowiedź, nowa linia (pusta), itd.
    """
    faq_entries = []
    lines = file_content.decode('utf-8').splitlines()
    
    current_question = None
    
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: # Pusta linia oddziela pytania/odpowiedzi
            current_question = None
            continue
        
        if stripped_line.lower().startswith("pytanie:"):
            current_question = stripped_line[len("pytanie:"):].strip()
        elif stripped_line.lower().startswith("odpowiedź:") and current_question:
            answer = stripped_line[len("odpowiedź:"):].strip()
            faq_entries.append({"pytanie": current_question, "odpowiedz": answer})
            current_question = None # Resetuj po dodaniu odpowiedzi
        else:
            # Jeśli linia nie pasuje do formatu "Pytanie: / Odpowiedź:", 
            # traktujemy linie jako pary Pytanie/Odpowiedź oddzielone pustą linią
            if current_question is None: # Jeśli to początek nowej pary (pytanie)
                current_question = stripped_line
            else: # Jeśli to odpowiedź na poprzednie pytanie
                faq_entries.append({"pytanie": current_question, "odpowiedz": stripped_line})
                current_question = None # Resetuj po dodaniu odpowiedzi

    return faq_entries


# --- Funkcje Asystenta ---

def describe_and_tag_image(image_bytes):
    """
    Opisuje zawartość zdjęcia i generuje tagi za pomocą Gemini 1.5 Flash.
    """
    image_part = {
        'mime_type': 'image/jpeg',
        'data': image_bytes
    }
    
    prompt_parts = [
        "Opisz szczegółowo zawartość tego zdjęcia, koncentrując się na opisach wszystkich obiektów, ilościach, opisach osób, akcjach, kolorach i ogólnym kontekście. Następnie, wygeneruj listę od 10 do 30 słów kluczowych (tagów) oddzielonych przecinkami, które najlepiej charakteryzują to zdjęcie. Format odpowiedzi: Opis: [Twój opis]. Tagi: [tag1, tag2, ...].",
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
    """Generuje sformatowany kontekst FAQ z danych w st.session_state."""
    faq_context = ""
    if st.session_state['faq_data']: 
        faq_context += "Kontekst FAQ:\n"
        for entry in st.session_state['faq_data']:
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
    Funkcja wywoływana po przesłaniu pytania w czacie.
    Zarządza historią rozmowy i generuje odpowiedzi.
    """
    user_question = st.session_state.chat_input # Pobierz pytanie z pola tekstowego

    if user_question:
        # Dodaj pytanie użytkownika do historii rozmowy
        st.session_state.messages.append({"role": "user", "content": user_question})
        
        # Przygotuj kontekst dla modelu (FAQ + opis zdjęcia)
        combined_context = get_faq_context() + get_image_context(
            st.session_state['image_description'],
            st.session_state['image_tags']
        )
        
        # Inicjalizacja lub resetowanie sesji czatu
        if 'chat_session' not in st.session_state or st.session_state.get('context_updated_flag', False):
            st.session_state.chat_session = model.start_chat(history=[
                {"role": "user", "parts": [
                    "Jesteś pomocnym asystentem AI. Odpowiadasz na pytania użytkownika, korzystając z kontekstu FAQ oraz/lub opisu i tagów przesłanego zdjęcia. Utrzymuj kontekst rozmowy. Jeśli pytanie nie pasuje do żadnego kontekstu, grzecznie poinformuj, że nie możesz pomóc i zaproponuj kontakt z obsługą klienta.",
                    combined_context
                ]},
                {"role": "model", "parts": ["Rozumiem. Jak mogę pomóc?"]}
            ])
            st.session_state['context_updated_flag'] = False # Zresetuj flagę po użyciu

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

def display_chat_messages():
    """Wyświetla wszystkie wiadomości z historii czatu."""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# --- Interfejs Streamlit ---

st.set_page_config(page_title="Asystent AI: Chatbot z FAQ i Zdjęciem", layout="centered")
st.title("🤖 Asystent AI: Chatbot z FAQ i Zdjęciem")
st.markdown("Witaj! Jestem chatbotem, który potrafi odpowiedzieć na pytania dotyczące FAQ (które możesz załadować!) lub przesłanego obrazu. Możesz ze mną swobodnie rozmawiać!")

# --- Inicjalizacja zmiennych stanu sesji ---
if 'messages' not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Cześć! Jestem Twoim asystentem. Jak mogę pomóc?"}]
if 'image_description' not in st.session_state:
    st.session_state['image_description'] = None
if 'image_tags' not in st.session_state:
    st.session_state['image_tags'] = None
if 'uploaded_image_bytes' not in st.session_state:
    st.session_state['uploaded_image_bytes'] = None
if 'uploaded_file_id' not in st.session_state: 
    st.session_state['uploaded_file_id'] = None
if 'chat_session' not in st.session_state:
    st.session_state['chat_session'] = None
if 'context_updated_flag' not in st.session_state:
    st.session_state['context_updated_flag'] = False
# Dodana zmienna dla danych FAQ załadowanych przez użytkownika
if 'faq_data' not in st.session_state:
    # Początkowo ładujemy FAQ z pliku, jeśli istnieje, lub jest puste
    try:
        # Próba wczytania domyślnego FAQ z pliku example_faq.txt
        with open("example_faq.txt", "r", encoding="utf-8") as f:
            st.session_state['faq_data'] = parse_faq_text(f.read().encode('utf-8'))
    except (FileNotFoundError):
        st.session_state['faq_data'] = []
    except Exception as e:
        st.warning(f"Nie udało się załadować domyślnego FAQ z example_faq.txt: {e}")
        st.session_state['faq_data'] = []


# --- Sekcja Ładowania FAQ ---
st.header("📚 Załaduj FAQ")
st.markdown("Możesz załadować plik tekstowy z pytaniami i odpowiedziami FAQ. Każda para pytanie-odpowiedź powinna być oddzielona pustą linią. Pytania i odpowiedzi mogą być prefiksowane 'Pytanie:' i 'Odpowiedź:', ale nie jest to wymagane.")

# Przycisk do pobierania przykładowego pliku FAQ
try:
    with open("example_faq.txt", "rb") as f:
        st.download_button(
            label="Pobierz przykładowe FAQ",
            data=f.read(),
            file_name="example_faq.txt",
            mime="text/plain"
        )
except FileNotFoundError:
    st.warning("Plik 'example_faq.txt' nie został znaleziony, nie można udostępnić przykładu.")

uploaded_faq_file = st.file_uploader("Wybierz plik tekstowy (.txt) z FAQ:", type=["txt"], key="faq_uploader")

if uploaded_faq_file is not None:
    # Sprawdź, czy to nowy plik FAQ, aby nie przetwarzać go na nowo przy każdej interakcji
    if st.session_state.get('uploaded_faq_file_id_faq') != uploaded_faq_file.file_id: # Zmieniono klucz id
        st.session_state['uploaded_faq_file_id_faq'] = uploaded_faq_file.file_id
        
        with st.spinner("Ładuję i parsuję FAQ..."):
            faq_content = uploaded_faq_file.read()
            parsed_faq = parse_faq_text(faq_content)
            
            if parsed_faq:
                st.session_state['faq_data'] = parsed_faq
                st.session_state['context_updated_flag'] = True # Flaga, że kontekst się zmienił
                st.success("FAQ załadowane pomyślnie!")
                st.markdown("#### Podgląd załadowanego FAQ:")
                for entry in parsed_faq[:5]: # Pokaż tylko pierwsze 5 dla podglądu
                    st.text(f"P: {entry['pytanie']}")
                    st.text(f"O: {entry['odpowiedz']}")
                    st.text("---")
                if len(parsed_faq) > 5:
                    st.text(f"...i {len(parsed_faq) - 5} więcej pytań.")
                st.rerun() # Odśwież, aby zainicjować chat z nowym kontekstem
            else:
                st.warning("Nie udało się sparsować FAQ. Sprawdź format pliku.")
                st.session_state['faq_data'] = [] # Wyczyść FAQ, jeśli błąd
                st.session_state['context_updated_flag'] = True # Flaga, że kontekst się zmienił


# --- Sekcja Przesyłania Zdjęć ---
st.header("📸 Prześlij Zdjęcie do Analizy")
uploaded_image_file = st.file_uploader("Wybierz zdjęcie (JPG, PNG):", type=["jpg", "jpeg", "png"], key="image_uploader")

if uploaded_image_file is not None:
    # Używamy unikalnego klucza dla ID pliku obrazu, aby nie kolidował z FAQ
    if st.session_state.get('uploaded_image_file_id') != uploaded_image_file.file_id:
        st.session_state['uploaded_image_file_id'] = uploaded_image_file.file_id
        st.session_state['uploaded_image_bytes'] = uploaded_image_file.getvalue()
        
        st.image(uploaded_image_file, caption='Przesłane zdjęcie', use_container_width=True)
        image_bytes = uploaded_image_file.getvalue()
        
        with st.spinner("Analizuję zdjęcie za pomocą Gemini AI..."):
            description, tags = describe_and_tag_image(image_bytes)
            st.session_state['image_description'] = description
            st.session_state['image_tags'] = tags
            
            st.subheader("Opis zdjęcia:")
            st.write(st.session_state['image_description'])
            st.subheader("Słowa kluczowe (tagi):")
            st.code(st.session_state['image_tags'])
            
            st.session_state.messages.append({"role": "assistant", "content": f"Przeanalizowałem to zdjęcie: {description}. Tag: {tags}. Teraz możesz zadawać mi pytania na jego temat."})
            st.session_state['context_updated_flag'] = True 
            st.rerun() # Odśwież, aby zainicjować chat z nowym kontekstem
    else: # Jeśli plik już był przesłany w tej sesji
        st.image(uploaded_image_file, caption='Przesłane zdjęcie', use_container_width=True)
        st.subheader("Opis zdjęcia:")
        st.write(st.session_state['image_description'])
        st.subheader("Słowa kluczowe (tagi):")
        st.code(st.session_state['image_tags'])

# --- Sekcja Chatbota ---
st.header("💬 Rozmowa z Asystentem")

# Wyświetlanie historii rozmowy
display_chat_messages()

# Pole wprowadzania pytania na dole
st.text_input(
    "Wpisz swoje pytanie (naciśnij Enter):", 
    key="chat_input", 
    on_change=chat_with_bot, 
    placeholder="Zapytaj o FAQ, zdjęcie lub cokolwiek..."
)