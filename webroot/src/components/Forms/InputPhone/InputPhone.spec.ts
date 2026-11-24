//
//  InputPhone.spec.ts
//  InspiringApps modules
//
//  Created by InspiringApps on 6/19/2020.
//

import { expect } from 'chai';
import { mountShallow, mountFull } from '@tests/helpers/setup';
import InputPhone from '@components/Forms/InputPhone/InputPhone.vue';
import { FormInput } from '@models/FormInput/FormInput.model';
import Joi from 'joi';
import { nextTick, reactive } from 'vue';

const createFormInput = (value = '', validation = Joi.string().required()) => new FormInput({
    id: 'phone',
    name: 'phone',
    label: 'Phone',
    value,
    validation,
});

describe('InputPhone component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(InputPhone, {
            props: {
                formInput: new FormInput(),
            },
        });

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(InputPhone).exists()).to.equal(true);
    });
    it('should display an initial E.164 value in national format', async () => {
        const wrapper = await mountFull(InputPhone, {
            props: { formInput: createFormInput('+13035551234') },
        });

        expect((wrapper.find('#phone').element as HTMLInputElement).value).to.equal('(303) 555-1234');
        expect(wrapper.vm.formData.country.value).to.equal('US');
    });
    it('should emit the E.164 value when entering the national number', async () => {
        const formInput = createFormInput();
        const wrapper = await mountFull(InputPhone, { props: { formInput }});
        const input = wrapper.find('#phone');

        await input.setValue('3035551234');

        expect(formInput.value).to.equal('+13035551234');

        await input.trigger('blur');

        expect((input.element as HTMLInputElement).value).to.equal('(303) 555-1234');
        expect(formInput.isValid).to.equal(true);
        expect(formInput.errorMessage).to.equal('');
    });
    it('should update the display when the value is changed externally', async () => {
        const formInput = reactive(createFormInput());
        const wrapper = await mountFull(InputPhone, { props: { formInput }});
        const input = wrapper.find('#phone');

        formInput.value = '+13035550100';
        await nextTick();

        expect((input.element as HTMLInputElement).value).to.equal('(303) 555-0100');

        formInput.value = '';
        await nextTick();

        expect((input.element as HTMLInputElement).value).to.equal('');
    });
    it('should show an error for an invalid number once touched', async () => {
        const formInput = createFormInput();
        const wrapper = await mountFull(InputPhone, { props: { formInput }});
        const input = wrapper.find('#phone');

        await input.setValue('3031111111');
        await input.trigger('blur');

        expect(formInput.isValid).to.equal(false);
        expect(formInput.errorMessage).to.equal(
            'Must be a valid phone number, including area code, for the selected country'
        );
    });
    it('should allow an empty optional number', async () => {
        const formInput = createFormInput('', Joi.string().allow(''));
        const wrapper = await mountFull(InputPhone, { props: { formInput }});

        await wrapper.find('#phone').trigger('blur');

        expect(formInput.isValid).to.equal(true);
        expect(formInput.errorMessage).to.equal('');
    });
});
