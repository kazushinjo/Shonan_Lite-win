#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

void reverse_words(const char *input_file, const char *output_file) {
    FILE *infile = fopen(input_file, "rb");
    FILE *outfile = fopen(output_file, "wb");
    if (!infile || !outfile) {
        perror("File opening failed");
        return;
    }

    fseek(infile, 0, SEEK_END);
    long file_size = ftell(infile);
    fseek(infile, 0, SEEK_SET);

    size_t num_words = file_size / sizeof(uint32_t);
    uint32_t *words = malloc(file_size);
    fread(words, sizeof(uint32_t), num_words, infile);

    for (int i = num_words -1; i >= 0; i--) {
        fwrite(&words[i], sizeof(uint32_t), 1, outfile);
    }

    free(words);
    fclose(infile);
    fclose(outfile);
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input_file> <output_file>\n", argv[0]);
        return EXIT_FAILURE;
    }

    reverse_words(argv[1], argv[2]);
    return EXIT_SUCCESS;
}