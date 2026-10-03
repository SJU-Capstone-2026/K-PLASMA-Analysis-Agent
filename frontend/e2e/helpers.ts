import type {Page} from '@playwright/test';
export async function navigate(page:Page,view:string){
 if(page.viewportSize()!.width<760)await page.getByRole('button',{name:'메뉴 열기'}).click();
 if(['catalog','flow'].includes(view))await page.locator('.nav-tools summary').click();
 await page.locator(`.nav-stack [data-view="${view}"]`).click();
}
