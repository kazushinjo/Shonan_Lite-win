#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <sys/select.h>
#include <signal.h>
#include <linux/input.h>

int hfd;

int hmiAvailable();
int getHmi();
int initHmi(char * hpath);


int initHmi(char * hpath)
{
        if ((hfd = open(hpath, O_RDONLY)) < 0) 
        {
                printf("HMI Open failed\n");
                return 1;
        }
        else
        {
                printf("HMI Open OK\n");
                return 0;
        }
}

//Returns 0 if no HMI Input available 1 if Volume Down is pressed

int getHmi()
{
  int i;
  size_t rb;
  struct input_event ev[64];
  int retval;
  
  retval=0;
  if(hmiAvailable())
    {
    rb=read(hfd,ev,sizeof(struct input_event)*64);
        for (i = 0;  i <  (rb / sizeof(struct input_event)); i++)
        {
          if((ev[i].type == 1) && (ev[i].code == 114))                       //volume down button
           {
              retval = ev[i].value + 1;                                      //1 = released 2 = pressed
           }
	    }
    }
  return retval;

}


int hmiAvailable()  
{
  struct timeval tv;
  fd_set fds;
  tv.tv_sec = 0;
  tv.tv_usec = 0;
  FD_ZERO(&fds);
  FD_SET(hfd, &fds);
  select(hfd+1, &fds, NULL, NULL, &tv);
  return (FD_ISSET(hfd, &fds));
}