#include<stdio.h>
#include<string.h>

struct personTag{
    char name[20];
    int age;
};
struct courseTag{
    int year;
    char grade;
};
struct studentTag{
    struct personTag studentInfo;
    struct courseTag SC1008;
};
struct studentTag students[3]={
    {{"harry",20},
    {1,'A'}},
    {{"messi",21},
    {1,'B'}},
    {{"ronaldo",19},
    {2,'A'}}    
};

int main()
{
    for(int i=0;i<3;i++)
    {
        printf("name:%s\n",students[i].studentInfo.name);
        printf("age:%d\n",students[i].studentInfo.age);
        printf("year:%d\n",students[i].SC1008.year);
        printf("grade:%c\n",students[i].SC1008.grade);
        printf("\n");
    }
    return 0;
}   

