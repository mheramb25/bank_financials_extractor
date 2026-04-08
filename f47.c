#include<stdio.h>
#include<string.h>

struct book
{
    char title[40];
    char author[20];
    float value;
    
};
int main()
{
    struct book bookrec={"alchemist","paulo coelho",200.50};\
    //i want to print the title and author of bookrec using pointer
    struct book *ptr;
    
    ptr=&bookrec;
    printf("the title of book is:%s\n",ptr->title);
    printf("the author of book is:%s\n",ptr->author);

    return 0;
}

