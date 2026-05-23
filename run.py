import os

# Run everything relative to the project root so config.yml and repos/ resolve
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from src.main import main

if __name__ == "__main__":
    main()
