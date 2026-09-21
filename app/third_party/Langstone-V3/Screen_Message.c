#include "Graphics.h"

#define MAX_FILENAME_LENGTH 255

int screenrotate = 0;
int V2Display =0 ;


void showMessage(char * msg);
void setRotation(int rot);
int readConfig(void);
FILE *openFile( char *fn );

int main(int argc, char* argv[])
{
  readConfig();
  setRotation(screenrotate);
  initScreen();
  setBackColour(0,0,0);
  clearScreen();
  setForeColour(0,255,255);
  textSize = 4;  
  int y=100;
  int l = 1;
  while(argc > 1)
  {
    int p = strlen(argv[l]) * 32;
    gotoXY(400 - (p/2),y);
    displayStr(argv[l++]); 
    argc--;
    y=y+80;
  }

}


void setRotation(int rot)
{
  rotateScreen(rot);
}


int readConfig(void)
{
    FILE * conffile;
    char variable[50];
    char value[100];
    char vname[20];

    conffile = openFile("Langstone/Langstone_Pluto.conf");
    if( conffile == NULL )
    {
        conffile = openFile("Langstone/Langstone_Hack.conf");
        if(conffile == NULL )
            return -1;
    }

    while (fscanf(conffile, "%49s %99s [^\n]\n", variable, value) !=EOF)
    {
        if (strstr(variable, "RotateScreen"))
            sscanf(value, "%d", &screenrotate);
    }

    fclose(conffile);
    return 0;
}


FILE *openFile(char *fn)
{
    char filename[MAX_FILENAME_LENGTH] = {0};
    int fnlen = 0;

    /* find user path i.e. /home/pi */
    char *userpath = getenv("HOME");
    if (userpath == NULL)
    {
        printf("Can read $HOME env variable");      // TODO: Move to separate logfile
        return NULL;
    }

    /* allocate space for filename */
    fnlen = snprintf(NULL, 0, "%s/%s", userpath, fn);
    if (fnlen > MAX_FILENAME_LENGTH)
    {
        printf("Filename greater than %i characters\n", MAX_FILENAME_LENGTH);       // TODO: Move to separate logfile
        return NULL;
    }

    memset(filename, 0, MAX_FILENAME_LENGTH);       // trust no one

    /* put it all together */
    int retval = snprintf(filename, MAX_FILENAME_LENGTH, "%s/%s", userpath, fn);
    if (retval != fnlen)
    {
        printf("Can't generate filename correctly, ignored\n");     // TODO: Move to separate logfile
        return NULL;
    }

    /* try to get file handle */
    return fopen(filename,"r");
}