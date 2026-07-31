from src.core.jarvis import Jarvis


def main():
    jarvis = Jarvis()

    print("=== Jarvis Başlatıldı ===")

    while True:
        prompt = input("\nSen: ")

        if prompt.lower() in ["çık", "exit", "quit"]:
            print("Jarvis kapatılıyor...")
            break

        cevap = jarvis.chat(prompt)

        print("\nJarvis:")
        print(cevap)


if __name__ == "__main__":
    main()