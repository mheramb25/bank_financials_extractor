#include<stdio.h>

int main()
{
    int len;
    printf("enter the length of array:\n");
    scanf("%d",&len);

    int arr1[len];
    for(int i=0;i<len;i++)
    {
        printf("enter nos.\n");
        scanf("%d",&arr1[i]);
    }
    int lindex=0;
    int sindex=0;
    int large=arr1[0];
    int small=arr1[0];


    for(int i=1;i<len;i++)
    {
        if(arr1[i]>large)
        {
            large=arr1[i];
            lindex=i;
        }
        if(arr1[i]<small)
        {
            small=arr1[i];
            sindex=i;
        }
    }
    printf("the largest number is:%d\n",large);
    printf("the index of largest number is:%d\n",lindex);
    printf("the smallest number is:%d\n",small);
    printf("the index of smallest number is:%d\n",sindex);
     
    return 0;
}